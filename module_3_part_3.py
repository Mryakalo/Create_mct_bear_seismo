"""
module_3_part_3.py — Модуль 3, Часть 3: боковое давление грунта на элементы опоры.

Алгоритм (одинаков для направлений Y и Z):

  1. Отбор элементов, у которых хотя бы один узел попадает в диапазон
     [z_bottom .. z_surface] зоны бокового давления грунта.

  2. Классификация отобранных элементов по типу:
     «сваи» / «ростверк» / «тело опоры» — через _classify_element()
     из additional_functions.py.

  3. Линейная интерполяция ширины сечения по Z для каждого узла элемента.
     Ширина берётся из SoilInfluence по section_number элемента (аналогично
     _mean_area_for_element из additional_functions).

  4. Вычисление активного давления грунта в узлах:
       p(z) = γ · Ka · h(z),  где  Ka = tan²(45° − φ/2),  h = z_surface − z_node
     Давление в узлах ниже z_bottom и выше z_surface = 0.

  5. Результирующая нагрузка на конец элемента:
       q_node = p(z_node) · width(z_node)   [тс/м]
     Запоминается пара (q_i, q_j) для каждого элемента — трапециевидная эпюра.

Публичный API:
    generate_lateral_pressure(model, pier, soil) -> LateralPressureResult

Структуры данных (добавить в data_structures.py):
    ElemPressureEntry  — нагрузка на один элемент (q в узлах i и j)
    LateralPressureResult — результат Части 3 для одной опоры
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from additional_functions import (
    _classify_element,
    _elem_z_range,
    _ELEM_TYPE_PILE,
    _ELEM_TYPE_FOOTING,
    _ELEM_TYPE_BODY, _width_at_z_for_node, _active_pressure_at_z, _active_pressure_coeff,
)
from data_structures import (
    Element,
    PierGeometry,
    PierModel,
    SoilInfluence, ElemPressureEntry, LateralPressureResult,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ядро: обработка одного направления (Y или Z)
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_pressure_for_direction(
    model: PierModel,
    pier: PierGeometry,
    soil: SoilInfluence,
    direction: str,              # 'y' или 'z'
    z_surface: float,
    z_bottom: float,
    gamma: float,
    ka: float,
    warnings: list[str],
) -> list[ElemPressureEntry]:
    """
    Вычисляет боковое давление грунта для всех элементов модели
    в заданном направлении (y / z).

    Шаги:
      1. Отбор элементов с хотя бы одним узлом в [z_bottom, z_surface].
      2. Классификация: сваи / ростверк / тело опоры.
      3. Определение ширины сечения в узлах i и j (линейная интерполяция).
      4. Вычисление активного давления и нагрузки в узлах.

    Возвращает список ElemPressureEntry.
    """
    entries: list[ElemPressureEntry] = []

    for eid, elem in model.elements.items():
        node_i = model.nodes.get(elem.node_i)
        node_j = model.nodes.get(elem.node_j)
        if node_i is None or node_j is None:
            warnings.append(
                f'  ⚠  [{pier.pier_name}] элемент {eid}: '
                f'узел не найден в модели — пропущен'
            )
            continue

        z_i = node_i.z
        z_j = node_j.z
        z_min = min(z_i, z_j)
        z_max = max(z_i, z_j)

        # ── Шаг 1: отбор элементов ───────────────────────────────────────────
        # Элемент попадает в зону воздействия, если хотя бы один его узел
        # находится в пределах [z_bottom, z_surface].
        if z_max < z_bottom or z_min > z_surface:
            continue

        # ── Шаг 2: классификация ─────────────────────────────────────────────
        elem_type = _classify_element(elem, pier)

        # ── Шаг 3: ширина в узлах ────────────────────────────────────────────
        width_i = _width_at_z_for_node(z_i, elem, elem_type, pier, soil, warnings)
        width_j = _width_at_z_for_node(z_j, elem, elem_type, pier, soil, warnings)

        if width_i is None or width_j is None:
            continue   # предупреждение уже добавлено внутри функции

        # ── Шаг 4: давление и нагрузка в узлах ──────────────────────────────
        # Давление вычисляется строго в пределах зоны [z_bottom, z_surface].
        # Для узлов вне зоны давление = 0 (обеспечивается _active_pressure_at_z).
        pressure_i = _active_pressure_at_z(z_i, z_surface, z_bottom, gamma, ka)
        pressure_j = _active_pressure_at_z(z_j, z_surface, z_bottom, gamma, ka)

        q_i = pressure_i * width_i   # тс/м
        q_j = pressure_j * width_j   # тс/м

        # Элемент добавляем только если хотя бы одно из значений q > 0
        if q_i <= 0.0 and q_j <= 0.0:
            continue

        entries.append(ElemPressureEntry(
            elem_id=eid,
            node_i=elem.node_i,
            node_j=elem.node_j,
            z_i=z_i,
            z_j=z_j,
            width_i=width_i,
            width_j=width_j,
            pressure_i=pressure_i,
            pressure_j=pressure_j,
            q_i=q_i,
            q_j=q_j,
            direction=direction,
            elem_type=elem_type,
        ))

    return entries


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичный API
# ═══════════════════════════════════════════════════════════════════════════════

def generate_lateral_pressure(
    model: PierModel,
    pier: PierGeometry,
    soil: SoilInfluence,
) -> LateralPressureResult:
    """
    Генерирует боковое давление грунта на элементы опоры.

    Обрабатывает оба направления (Y и Z) независимо, только если
    соответствующий флаг в SoilInfluence установлен (lateral_pressure_y/z_present).

    Параметры:
        model  — КЭ-модель опоры (PierModel) с заполненными nodes и elements.
        pier   — геометрические параметры опоры (PierGeometry).
        soil   — грунтовые параметры (SoilInfluence).

    Возвращает LateralPressureResult:
        entries_y — список ElemPressureEntry для нагрузок по оси Y.
        entries_z — список ElemPressureEntry для нагрузок по оси Z.
        warnings  — диагностические сообщения.

    Не печатает ничего — вывод делает main.
    """
    result = LateralPressureResult(pier_name=pier.pier_name)

    # ── Проверка общих параметров грунта ─────────────────────────────────────
    gamma = soil.pressure_unit_weight
    phi   = soil.pressure_friction_angle

    if gamma is None or phi is None:
        if soil.lateral_pressure_y_present or soil.lateral_pressure_z_present:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] боковое давление: '
                f'не заданы γ или φ — вычисление невозможно'
            )
        return result

    ka = _active_pressure_coeff(phi)

    # ── Направление Y ────────────────────────────────────────────────────────
    if soil.lateral_pressure_y_present:
        z_surf_y = soil.pressure_y_z_surface
        z_bot_y  = soil.pressure_y_z_bottom

        if z_surf_y is None or z_bot_y is None:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] боковое давление Y: '
                f'не заданы z_surface или z_bottom — направление Y пропущено'
            )
        elif z_surf_y <= z_bot_y:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] боковое давление Y: '
                f'z_surface ({z_surf_y:.3f}) ≤ z_bottom ({z_bot_y:.3f}) — '
                f'направление Y пропущено'
            )
        else:
            result.entries_y = _compute_pressure_for_direction(
                model=model,
                pier=pier,
                soil=soil,
                direction='y',
                z_surface=z_surf_y,
                z_bottom=z_bot_y,
                gamma=gamma,
                ka=ka,
                warnings=result.warnings,
            )

    # ── Направление Z ────────────────────────────────────────────────────────
    if soil.lateral_pressure_z_present:
        z_surf_z = soil.pressure_z_z_surface
        z_bot_z  = soil.pressure_z_z_bottom

        if z_surf_z is None or z_bot_z is None:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] боковое давление Z: '
                f'не заданы z_surface или z_bottom — направление Z пропущено'
            )
        elif z_surf_z <= z_bot_z:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] боковое давление Z: '
                f'z_surface ({z_surf_z:.3f}) ≤ z_bottom ({z_bot_z:.3f}) — '
                f'направление Z пропущено'
            )
        else:
            result.entries_z = _compute_pressure_for_direction(
                model=model,
                pier=pier,
                soil=soil,
                direction='z',
                z_surface=z_surf_z,
                z_bottom=z_bot_z,
                gamma=gamma,
                ka=ka,
                warnings=result.warnings,
            )

    return result

"""
module_3_part1.py — Модуль 3, Часть 1: Нагрузки и массы от пролётных строений.

Генерирует нагрузки и массы для двух расчётных схем:

  Схема 1 — только постоянные нагрузки:
    • ConcentratedLoad (FZ < 0) в узлах z = z_cg каждой ОЧ (правой и левой отдельно)
    • NodalMass (mx, my, mz) в узлах, соответствующих отметкам из листа «Массы»
      (r_mx_z, r_my_z, r_mz_z, l_mx_z, l_my_z, l_mz_z) — по каждой ОЧ отдельно

  Схема 2 — постоянные + временные нагрузки:
    • Всё из Схемы 1 ПЛЮС
    • ConcentratedLoad (FZ < 0) в узлах z = z_road каждой ОЧ (временные)
    • NodalMass доп. временных масс (r_mx_t_z, r_my_t_z, … l_mz_t_z) — по каждой ОЧ отдельно

КЛЮЧЕВАЯ ЛОГИКА (исправлено):
--------------------------------
Нагрузки и массы прикладываются ОТДЕЛЬНО для каждой опорной части (ОЧ):
  - Правая ОЧ (right): значение r_R_perm → узел (x_frame, y=0, z=z_cg_right)
  - Левая ОЧ  (left):  значение l_R_perm → узел (x_frame, y=0, z=z_cg_left)

При наличии двух рамок (Плеть 1 и Плеть 2 на одной опоре) каждая рамка
обрабатывается независимо с собственными z_cg/z_road и x_frame.

Логика поиска узлов
-------------------
Узел выбирается из model.nodes по (x, y=0, z):
  x — x_coordinate рамки (FrameResult / FrameParameters)
  y — 0.0          (ось симметрии; нагрузки прикладываются в ось)
  z — требуемая отметка (z_cg, z_road, или отметка из «Массы»)

Если точного совпадения (x, y=0, z) нет — берётся ближайший узел
по Z (при x ≈ x_frame, y ≈ 0), и в warnings записывается предупреждение.
Если вообще нет ни одного подходящего узла — ошибка, нагрузка пропускается.

Публичный API
-------------
  generate_span_loads(pier, pier_model, bearing_rows, masses_rows)
      -> Part3Result

  Возвращает Part3Result, заполняя:
    permanent_loads   — нагрузки Схемы 1
    permanent_masses  — массы Схемы 1
    temporary_loads   — нагрузки Схемы 2 (постоянные + временные)
    temporary_masses  — массы Схемы 2 (постоянные + временные)

  Остальные поля Part3Result (грунтовые, вода и т.д.) заполняются
  в следующих частях Модуля 3 и здесь не трогаются.
"""

from __future__ import annotations

import math
from typing import Optional

from data_structures import (
    BearingPlaneRow,
    MassesRow,
    PierGeometry,
    PierModel,
    Node,
    ConcentratedLoad,
    NodalMass,
    Part3Result,
)

# ── Допуск совпадения координат (идентичен additional_functions) ──────────────
_COORD_TOL = 1e-6   # м — для точного совпадения
_Z_SNAP_TOL = 0.05  # м — допуск «ближайшего» узла по Z (snap-fallback)


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции поиска узлов
# ═══════════════════════════════════════════════════════════════════════════════

def _node_at_xyz_axis(
    model: PierModel,
    x: float,
    z: float,
) -> Optional[int]:
    """
    Ищет узел с координатами (x, y=0, z) в оси рамки.

    Допуск _COORD_TOL для x и z, y строго равно 0 (ось).
    Возвращает node_id или None.
    """
    for node in model.nodes.values():
        if (math.isclose(node.x, x, abs_tol=_COORD_TOL)
                and math.isclose(node.y, 0.0, abs_tol=_COORD_TOL)
                and math.isclose(node.z, z, abs_tol=_COORD_TOL)):
            return node.node_id
    return None


def _nearest_node_at_x_z(
    model: PierModel,
    x: float,
    z: float,
) -> tuple[Optional[int], float]:
    """
    Находит ближайший к (x, y=0, z) узел в оси рамки (y ≈ 0).

    Сортирует по |dz|, при равенстве — по |dx|.
    Возвращает (node_id, delta_z) или (None, inf).
    """
    candidates = [
        n for n in model.nodes.values()
        if math.isclose(n.y, 0.0, abs_tol=_COORD_TOL)
        and math.isclose(n.x, x, abs_tol=_COORD_TOL)
    ]
    if not candidates:
        return None, math.inf

    best = min(candidates, key=lambda n: abs(n.z - z))
    return best.node_id, abs(best.z - z)


def _resolve_node(
    model: PierModel,
    x: float,
    z: float,
    label: str,
    warnings: list[str],
    errors: list[str],
) -> Optional[int]:
    """
    Возвращает node_id для точки (x, y=0, z).

    1. Точный поиск (_COORD_TOL).
    2. Snap-fallback: ближайший узел по Z в той же рамке (x) — если dz < _Z_SNAP_TOL.
    3. Если ничего — None + ошибка.
    """
    nid = _node_at_xyz_axis(model, x, z)
    if nid is not None:
        return nid

    snap_id, dz = _nearest_node_at_x_z(model, x, z)
    if snap_id is not None and dz < _Z_SNAP_TOL:
        warnings.append(
            f'[{label}] нет узла (x={x:.3f}, y=0, z={z:.3f}) — '
            f'используется ближайший node_id={snap_id} (dz={dz:.4f} м)'
        )
        return snap_id

    errors.append(
        f'[{label}] не найден узел (x={x:.3f}, y=0, z={z:.3f}) — '
        f'нагрузка/масса пропущена'
    )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Получение строк «Плеть» для рамки опоры
# ═══════════════════════════════════════════════════════════════════════════════

def _rows_for_frame(
    pier_name: str,
    frame_number: int,
    bearing_rows: list[BearingPlaneRow],
) -> list[BearingPlaneRow]:
    """
    Возвращает строки листа «Плеть» для данной рамки данной опоры.

    Строки группируются по span_group_name.
    Рамка 1 → первая группа (лексикографически), Рамка 2 → вторая группа (если есть).

    Если у опоры только одна плеть — все строки относятся к рамке 1.
    """
    pier_rows = [r for r in bearing_rows if r.pier_name == pier_name]
    if not pier_rows:
        return []

    groups: dict[str, list[BearingPlaneRow]] = {}
    for r in pier_rows:
        groups.setdefault(r.span_group_name, []).append(r)

    sorted_group_keys = sorted(groups.keys())  # лексикографически: «Плеть 1» < «Плеть 2»

    if frame_number <= len(sorted_group_keys):
        return groups[sorted_group_keys[frame_number - 1]]
    return []


# ═══════════════════════════════════════════════════════════════════════════════
#  Генерация нагрузок (ConcentratedLoad) — ИСПРАВЛЕНО
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_loads_for_frame(
    pier_name: str,
    frame_number: int,
    x_frame: float,
    bearing_rows_for_frame: list[BearingPlaneRow],
    model: PierModel,
    permanent_loads: list[ConcentratedLoad],
    temporary_loads: list[ConcentratedLoad],
    warnings: list[str],
    errors: list[str],
) -> None:
    """
    Добавляет нагрузки от одной рамки в списки permanent_loads и temporary_loads.

    ИСПРАВЛЕНИЕ: нагрузки прикладываются ОТДЕЛЬНО для каждой ОЧ (правой и левой)
    с использованием z_cg и z_road из соответствующей строки «Плеть».

    Правая ОЧ → r_R_perm / r_R_temp → узел (x_frame, 0, z_cg_right / z_road_right)
    Левая ОЧ  → l_R_perm / l_R_temp → узел (x_frame, 0, z_cg_left  / z_road_left)

    Таким образом, если у строки правая и левая ОЧ имеют разные z_cg или z_road,
    нагрузки попадают в разные узлы.
    """
    for row in bearing_rows_for_frame:
        z_cg   = row.z_cg_elevation
        z_road = row.z_road_elevation

        if z_cg is None:
            errors.append(
                f'[{pier_name}/рамка{frame_number}/строка_bearing{row.right_bearing_number}] '
                f'не задан z_cg — постоянные нагрузки пропущены'
            )
            continue

        # ── Правая ОЧ: постоянная нагрузка → z_cg ───────────────────────────
        r_perm = row.right_load_permanent or 0.0
        if abs(r_perm) > 1e-12:
            label = f'{pier_name}/рамка{frame_number}/ОЧ{row.right_bearing_number}/постоянная'
            nid = _resolve_node(model, x_frame, z_cg, label, warnings, errors)
            if nid is not None:
                permanent_loads.append(ConcentratedLoad(
                    node_id=nid,
                    direction='FZ',
                    value=-abs(r_perm),   # вниз = отрицательная FZ
                ))

        # ── Левая ОЧ: постоянная нагрузка → z_cg ────────────────────────────
        l_perm = row.left_load_permanent or 0.0
        if abs(l_perm) > 1e-12:
            label = f'{pier_name}/рамка{frame_number}/ОЧ{row.left_bearing_number}/постоянная'
            nid = _resolve_node(model, x_frame, z_cg, label, warnings, errors)
            if nid is not None:
                permanent_loads.append(ConcentratedLoad(
                    node_id=nid,
                    direction='FZ',
                    value=-abs(l_perm),   # вниз = отрицательная FZ
                ))

        # ── Временные нагрузки: только если z_road задан ────────────────────
        if z_road is None:
            errors.append(
                f'[{pier_name}/рамка{frame_number}/строка_bearing{row.right_bearing_number}] '
                f'не задан z_road — временные нагрузки пропущены'
            )
            continue

        # ── Правая ОЧ: временная нагрузка → z_road ──────────────────────────
        r_temp = row.right_load_temporary or 0.0
        if abs(r_temp) > 1e-12:
            label = f'{pier_name}/рамка{frame_number}/ОЧ{row.right_bearing_number}/временная'
            nid = _resolve_node(model, x_frame, z_road, label, warnings, errors)
            if nid is not None:
                temporary_loads.append(ConcentratedLoad(
                    node_id=nid,
                    direction='FZ',
                    value=-abs(r_temp),   # вниз = отрицательная FZ
                ))

        # ── Левая ОЧ: временная нагрузка → z_road ───────────────────────────
        l_temp = row.left_load_temporary or 0.0
        if abs(l_temp) > 1e-12:
            label = f'{pier_name}/рамка{frame_number}/ОЧ{row.left_bearing_number}/временная'
            nid = _resolve_node(model, x_frame, z_road, label, warnings, errors)
            if nid is not None:
                temporary_loads.append(ConcentratedLoad(
                    node_id=nid,
                    direction='FZ',
                    value=-abs(l_temp),   # вниз = отрицательная FZ
                ))


# ═══════════════════════════════════════════════════════════════════════════════
#  Генерация масс (NodalMass)
# ═══════════════════════════════════════════════════════════════════════════════

def _accumulate_nodal_mass(
    masses_dict: dict[int, NodalMass],
    node_id: int,
    mx: float = 0.0,
    my: float = 0.0,
    mz: float = 0.0,
) -> None:
    """Добавляет компоненты массы к узлу node_id (создаёт запись при необходимости)."""
    if node_id not in masses_dict:
        masses_dict[node_id] = NodalMass(node_id=node_id)
    entry = masses_dict[node_id]
    entry.mx += mx
    entry.my += my
    entry.mz += mz


def _generate_masses_for_bearing_side(
    pier_name: str,
    frame_number: int,
    side: str,                   # 'right' | 'left'
    x_frame: float,
    mass_row: MassesRow,
    model: PierModel,
    permanent_masses_dict: dict[int, NodalMass],
    temporary_masses_dict: dict[int, NodalMass],
    warnings: list[str],
    errors: list[str],
) -> None:
    """
    Добавляет постоянные и временные массы для одной стороны (right/left) ОЧ.

    ИСПРАВЛЕНИЕ: каждая ОЧ обрабатывается строго по своим данным из MassesRow.
    Правая и левая ОЧ могут иметь разные z-отметки и попадают в разные узлы.

    Каждая компонента (mx, my, mz) может иметь свою отметку Z —
    они берутся из MassesRow (r_mx_z, r_my_z, r_mz_z и аналоги для левой стороны).
    """
    bearing_no = (
        mass_row.right_bearing_number if side == 'right'
        else mass_row.left_bearing_number
    )
    prefix = f'{pier_name}/рамка{frame_number}/ОЧ{bearing_no}/{side}'

    # ── Таблица: (масса, z_отметка, имя) для постоянных ─────────────────────
    if side == 'right':
        perm_components = [
            (mass_row.right_mass_X_permanent, mass_row.right_mass_X_z, 'mx_perm'),
            (mass_row.right_mass_Y_permanent, mass_row.right_mass_Y_z, 'my_perm'),
            (mass_row.right_mass_Z_permanent, mass_row.right_mass_Z_z, 'mz_perm'),
        ]
        temp_components = [
            (mass_row.right_mass_X_temporary, mass_row.right_mass_X_temp_z, 'mx_temp'),
            (mass_row.right_mass_Y_temporary, mass_row.right_mass_Y_temp_z, 'my_temp'),
            (mass_row.right_mass_Z_temporary, mass_row.right_mass_Z_temp_z, 'mz_temp'),
        ]
    else:  # left
        perm_components = [
            (mass_row.left_mass_X_permanent, mass_row.left_mass_X_z, 'mx_perm'),
            (mass_row.left_mass_Y_permanent, mass_row.left_mass_Y_z, 'my_perm'),
            (mass_row.left_mass_Z_permanent, mass_row.left_mass_Z_z, 'mz_perm'),
        ]
        temp_components = [
            (mass_row.left_mass_X_temporary, mass_row.left_mass_X_temp_z, 'mx_temp'),
            (mass_row.left_mass_Y_temporary, mass_row.left_mass_Y_temp_z, 'my_temp'),
            (mass_row.left_mass_Z_temporary, mass_row.left_mass_Z_temp_z, 'mz_temp'),
        ]

    # ── Постоянные массы ──────────────────────────────────────────────────────
    for (value, z_elev, name) in perm_components:
        if abs(value or 0.0) < 1e-12:
            continue
        if z_elev is None:
            errors.append(
                f'[{prefix}/{name}] не задана отметка Z — масса пропущена'
            )
            continue
        nid = _resolve_node(model, x_frame, z_elev, f'{prefix}/{name}', warnings, errors)
        if nid is None:
            continue
        if name == 'mx_perm':
            _accumulate_nodal_mass(permanent_masses_dict, nid, mx=value)
        elif name == 'my_perm':
            _accumulate_nodal_mass(permanent_masses_dict, nid, my=value)
        else:  # mz_perm
            _accumulate_nodal_mass(permanent_masses_dict, nid, mz=value)

    # ── Временные массы ───────────────────────────────────────────────────────
    for (value, z_elev, name) in temp_components:
        if abs(value or 0.0) < 1e-12:
            continue
        if z_elev is None:
            errors.append(
                f'[{prefix}/{name}] не задана отметка Z — масса пропущена'
            )
            continue
        nid = _resolve_node(model, x_frame, z_elev, f'{prefix}/{name}', warnings, errors)
        if nid is None:
            continue
        if name == 'mx_temp':
            _accumulate_nodal_mass(temporary_masses_dict, nid, mx=value)
        elif name == 'my_temp':
            _accumulate_nodal_mass(temporary_masses_dict, nid, my=value)
        else:  # mz_temp
            _accumulate_nodal_mass(temporary_masses_dict, nid, mz=value)


# ═══════════════════════════════════════════════════════════════════════════════
#  Главная функция Части 1 Модуля 3
# ═══════════════════════════════════════════════════════════════════════════════

def generate_span_loads(
    pier: PierGeometry,
    pier_model: PierModel,
    bearing_rows: list[BearingPlaneRow],
    masses_rows: list[MassesRow],
) -> Part3Result:
    """
    Генерирует нагрузки и массы от пролётных строений для одной опоры.

    Параметры
    ----------
    pier         : PierGeometry — геометрические параметры опоры (из Модуля 1)
    pier_model   : PierModel    — КЭ-модель опоры с узлами (из Модуля 2)
    bearing_rows : список BearingPlaneRow для всех опор (лист «Плеть»)
    masses_rows  : список MassesRow для всех опор (лист «Массы»)

    Возвращает
    ----------
    Part3Result с заполненными полями:
      permanent_loads   — нагрузки Схемы 1 (только постоянные)
      permanent_masses  — массы Схемы 1
      temporary_loads   — нагрузки Схемы 2 (постоянные + временные)
      temporary_masses  — массы Схемы 2
      warnings, errors  — диагностические сообщения
    """
    result = Part3Result()
    pier_name = pier.pier_name

    # ── Строки «Массы» для данной опоры ──────────────────────────────────────
    pier_mass_rows = [m for m in masses_rows if m.pier_name == pier_name]
    if not pier_mass_rows:
        result.warnings.append(
            f'[{pier_name}] нет строк в листе «Массы» — массы пропущены'
        )

    # Словари для накопления масс по node_id (потом конвертируются в списки)
    perm_masses_dict: dict[int, NodalMass] = {}
    temp_masses_dict: dict[int, NodalMass] = {}   # накапливает только временные массы

    # ── Определяем рамки ──────────────────────────────────────────────────────
    frames_params: list[tuple[int, float]] = []  # (frame_number, x_coordinate)

    if pier.geom_source == 'parametric':
        for frame_num, frame in enumerate([pier.frame1, pier.frame2], start=1):
            if frame is not None:
                frames_params.append((frame_num, frame.x_coordinate))
    else:
        # geom_source == 'mct': x-координату берём из узлов модели
        x_coords_at_y0 = sorted(set(
            round(n.x / _COORD_TOL) * _COORD_TOL
            for n in pier_model.nodes.values()
            if math.isclose(n.y, 0.0, abs_tol=_COORD_TOL)
        ))
        for frame_num, x_val in enumerate(x_coords_at_y0, start=1):
            frames_params.append((frame_num, x_val))

    if not frames_params:
        result.errors.append(
            f'[{pier_name}] не удалось определить рамки — нагрузки пропущены'
        )
        return result

    # ── Обрабатываем каждую рамку ────────────────────────────────────────────
    for frame_number, x_frame in frames_params:

        # Строки «Плеть» для этой рамки
        frame_bearing_rows = _rows_for_frame(pier_name, frame_number, bearing_rows)

        if not frame_bearing_rows:
            result.warnings.append(
                f'[{pier_name}/рамка{frame_number}] нет строк в «Плеть» — '
                f'нагрузки пропущены'
            )
            continue

        # ── Нагрузки: правая и левая ОЧ каждой строки — отдельно ────────────
        #
        # ИСПРАВЛЕНИЕ: передаём все строки рамки; внутри функции каждая
        # ОЧ (right / left) обрабатывается отдельно с использованием
        # своих z_cg и z_road из строки «Плеть».
        #
        # temporary_loads_frame — только временные нагрузки (добавляются в Схему 2)
        perm_loads_frame: list[ConcentratedLoad] = []
        temp_loads_frame: list[ConcentratedLoad] = []

        _generate_loads_for_frame(
            pier_name=pier_name,
            frame_number=frame_number,
            x_frame=x_frame,
            bearing_rows_for_frame=frame_bearing_rows,
            model=pier_model,
            permanent_loads=perm_loads_frame,
            temporary_loads=temp_loads_frame,
            warnings=result.warnings,
            errors=result.errors,
        )

        # Схема 1: только постоянные
        result.permanent_loads.extend(perm_loads_frame)

        # Схема 2: постоянные (копия) + временные
        result.temporary_loads.extend(perm_loads_frame)
        result.temporary_loads.extend(temp_loads_frame)

        # ── Массы ─────────────────────────────────────────────────────────────
        #
        # ИСПРАВЛЕНИЕ: строки MassesRow фильтруются по bearing_number,
        # принадлежащим данной рамке. Каждая строка MassesRow содержит
        # данные ровно для одной пары ОЧ (right_bearing_number, left_bearing_number).
        # Правая и левая ОЧ обрабатываются независимо.

        # Собираем номера ОЧ, задействованных в данной рамке
        bearing_numbers_in_frame: set[int] = set()
        for row in frame_bearing_rows:
            if row.right_bearing_number is not None:
                bearing_numbers_in_frame.add(row.right_bearing_number)
            if row.left_bearing_number is not None:
                bearing_numbers_in_frame.add(row.left_bearing_number)

        # Выбираем строки MassesRow для этой рамки:
        # строка относится к рамке, если её right_bearing_number ИЛИ
        # left_bearing_number принадлежит этой рамке.
        if bearing_numbers_in_frame:
            frame_mass_rows = [
                m for m in pier_mass_rows
                if (m.right_bearing_number in bearing_numbers_in_frame
                    or m.left_bearing_number in bearing_numbers_in_frame)
            ]
        else:
            frame_mass_rows = pier_mass_rows   # fallback: все строки

        for mass_row in frame_mass_rows:
            # Правая сторона ОЧ — только если её bearing_number в рамке
            if (mass_row.right_bearing_number is None
                    or mass_row.right_bearing_number in bearing_numbers_in_frame):
                _generate_masses_for_bearing_side(
                    pier_name=pier_name,
                    frame_number=frame_number,
                    side='right',
                    x_frame=x_frame,
                    mass_row=mass_row,
                    model=pier_model,
                    permanent_masses_dict=perm_masses_dict,
                    temporary_masses_dict=temp_masses_dict,
                    warnings=result.warnings,
                    errors=result.errors,
                )
            # Левая сторона ОЧ — только если её bearing_number в рамке
            if (mass_row.left_bearing_number is None
                    or mass_row.left_bearing_number in bearing_numbers_in_frame):
                _generate_masses_for_bearing_side(
                    pier_name=pier_name,
                    frame_number=frame_number,
                    side='left',
                    x_frame=x_frame,
                    mass_row=mass_row,
                    model=pier_model,
                    permanent_masses_dict=perm_masses_dict,
                    temporary_masses_dict=temp_masses_dict,
                    warnings=result.warnings,
                    errors=result.errors,
                )

    # ── Конвертируем словари масс в списки ───────────────────────────────────

    # Схема 1: только постоянные массы
    result.permanent_masses = list(perm_masses_dict.values())

    # Схема 2: постоянные + временные (объединяем по node_id)
    combined_masses: dict[int, NodalMass] = {}
    for nm in perm_masses_dict.values():
        combined_masses[nm.node_id] = NodalMass(
            node_id=nm.node_id, mx=nm.mx, my=nm.my, mz=nm.mz
        )
    for nm in temp_masses_dict.values():
        if nm.node_id in combined_masses:
            combined_masses[nm.node_id].mx += nm.mx
            combined_masses[nm.node_id].my += nm.my
            combined_masses[nm.node_id].mz += nm.mz
        else:
            combined_masses[nm.node_id] = NodalMass(
                node_id=nm.node_id, mx=nm.mx, my=nm.my, mz=nm.mz
            )
    result.temporary_masses = list(combined_masses.values())

    return result
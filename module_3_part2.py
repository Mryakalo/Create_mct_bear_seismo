"""
module_3_part2.py — Модуль 3, Часть 2: массы от воды и разжиженного грунта.

Алгоритм (одинаковый для воды и разжиженного грунта):

  0. Элементы КЭ-модели опоры уже разбиты на конечные элементы в Модуле 2.

  1. Определяется диапазон отметок [z_bot .. z_top] из SoilInfluence:
       — вода:        water_z_bottom   .. water_z_top
       — разжижение:  liquefaction_z_bottom .. liquefaction_z_top

  2. Из model.elements выбираются элементы, оба узла которых (или хотя бы
     один) попадают в диапазон. Элемент включается, если его отрезок
     пересекается с зоной [z_bot, z_top] (z_i или z_j лежит внутри, либо
     элемент перекрывает зону целиком).

  3. Каждый элемент классифицируется по типу: сваи / ростверк / тело опоры
     (стойка + ригель). Классификация выполняется по диапазонам id,
     задаваемым полями node_offset_* PierGeometry.

  4. Для каждого элемента вычисляется средняя площадь поперечного сечения
     методом линейной интерполяции между area_top и area_bottom зоны
     SectionZone (по SoilInfluence). Зона элемента определяется по его
     section_number, сопоставленному с зонами SoilInfluence.

     Площади сечений задаются парами (top/bottom) для каждой зоны:
       — ростверк:  footing_area_sec{1,2}_{top,bottom}
       — стойка:    column_area_sec{1,2,3}_{top,bottom}
       — сваи:      pile_area_{top,bottom}

  5. Масса элемента (тс·с²/м):
       m_elem = A_mean * L_elem * γ / g

     где:
       A_mean — средняя площадь сечения элемента (м²)
       L_elem — длина элемента, участвующая в зоне воздействия (м)
                (отсекается по z_bot / z_top, если элемент выходит за пределы)
       γ      — удельный вес воды/грунта (тс/м³)
       g      — ускорение свободного падения (м/с²)

  6. Масса делится пополам между узлами i и j элемента и прикладывается по
     направлениям X и Y (горизонтальные сейсмические массы).
     Одному узлу могут принадлежать несколько элементов — значения суммируются.

Результат:
  NodeMassEntry      — масса одного узла по одному источнику (вода / разжижение)
  FluidMassResult    — все записи для одной опоры + предупреждения
  build_fluid_masses — публичная функция, вызываемая из main

Вывод:
  print_fluid_masses_report — консольный отчёт для вызова из mct_generator.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from additional_functions import _overlap_length, _classify_element, _mean_area_for_element
from data_structures import (
    Element,
    Node,
    PierGeometry,
    PierModel,
    SoilInfluence, NodeMassEntry, FluidMassResult,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Основная функция вычисления масс для одного источника воздействия
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_fluid_masses(
    model:       PierModel,
    pier:        PierGeometry,
    soil:        SoilInfluence,
    z_bot:       float,
    z_top:       float,
    unit_weight: float,    # γ, тс/м³
    gravity:     float,    # g, м/с²
    source:      str,      # 'вода' | 'разжижение'
    warnings:    list[str],
) -> list[NodeMassEntry]:
    """
    Вычисляет горизонтальные сейсмические массы для зоны [z_bot, z_top].

    Возвращает список NodeMassEntry (по одной записи на узел на каждый
    примыкающий элемент; агрегирование по узлу — на уровне вызывающего кода).
    """
    if z_bot >= z_top:
        warnings.append(
            f'  ⚠  [{pier.pier_name}] {source}: '
            f'z_bottom={z_bot:.3f} >= z_top={z_top:.3f} — зона пуста, пропускается'
        )
        return []

    if unit_weight <= 0.0:
        warnings.append(
            f'  ⚠  [{pier.pier_name}] {source}: '
            f'удельный вес ≤ 0 ({unit_weight}) — пропускается'
        )
        return []

    if gravity <= 0.0:
        warnings.append(
            f'  ⚠  [{pier.pier_name}] {source}: '
            f'g ≤ 0 ({gravity}) — пропускается'
        )
        return []

    entries: list[NodeMassEntry] = []
    n_processed = 0

    for elem in model.elements.values():
        # ── Шаги 1–2: проверяем пересечение с зоной ──────────────────────────
        node_i = model.nodes.get(elem.node_i)
        node_j = model.nodes.get(elem.node_j)
        if node_i is None or node_j is None:
            warnings.append(
                f'  ⚠  [{pier.pier_name}] элемент {elem.elem_id}: '
                f'узел не найден в модели — пропущен'
            )
            continue

        z_i, z_j = node_i.z, node_j.z
        L_overlap = _overlap_length(z_i, z_j, z_bot, z_top)
        if L_overlap < 1e-9:
            continue   # элемент вне зоны

        # ── Шаг 3: тип элемента ───────────────────────────────────────────────
        elem_type = _classify_element(elem, pier)

        # ── Шаг 4: средняя площадь сечения ────────────────────────────────────
        # z_mid — середина участка пересечения элемента с зоной воздействия
        z_overlap_bot = max(min(z_i, z_j), z_bot)
        z_overlap_top = min(max(z_i, z_j), z_top)
        z_mid = (z_overlap_bot + z_overlap_top) / 2.0

        A_mean = _mean_area_for_element(
            elem=elem,
            elem_type=elem_type,
            soil=soil,
            z_mid=z_mid,
            pier=pier,
            warnings=warnings,
        )
        if A_mean is None:
            continue

        # ── Шаг 5: масса элемента ─────────────────────────────────────────────
        m_elem = A_mean * L_overlap * unit_weight / gravity   # тс·с²/м

        # ── Шаг 6: делим пополам между узлами i и j ───────────────────────────
        m_half = m_elem / 2.0

        for node in (node_i, node_j):
            entries.append(NodeMassEntry(
                node_id   = node.node_id,
                z         = node.z,
                mass_x    = m_half,
                mass_y    = m_half,
                source    = source,
                elem_type = elem_type,
            ))

        n_processed += 1

    if n_processed == 0 and not any(source in w for w in warnings):
        warnings.append(
            f'  ℹ  [{pier.pier_name}] {source}: '
            f'ни один элемент не попал в зону [{z_bot:.3f}; {z_top:.3f}]'
        )

    return entries


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция — точка входа из main
# ═══════════════════════════════════════════════════════════════════════════════

def build_fluid_masses(
    pier:    PierGeometry,
    model:   PierModel,
    soil:    SoilInfluence,
    gravity: float = 9.806,
) -> FluidMassResult:
    """
    Вычисляет горизонтальные сейсмические массы от воды и разжиженного грунта
    для одной опоры.

    Параметры
    ---------
    pier    — геометрия опоры (PierGeometry)
    model   — КЭ-модель опоры (PierModel), заполненная Модулем 2
    soil    — грунтовые воздействия (SoilInfluence) для данной опоры
    gravity — ускорение свободного падения, м/с² (из ProjectParameters)

    Возвращает FluidMassResult с полями:
      node_masses — список NodeMassEntry (несколько записей на узел суммируются
                    вызывающим кодом при записи в .mct)
      warnings    — диагностика
    """
    result = FluidMassResult(pier_name=pier.pier_name)

    if model is None:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] модель не сгенерирована — пропускается'
        )
        return result

    # ── Масса воды ────────────────────────────────────────────────────────────
    if soil.water_mass_present:
        if soil.water_z_bottom is None or soil.water_z_top is None:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] вода: '
                f'water_z_bottom или water_z_top не заданы — пропускается'
            )
        else:
            # Удельный вес воды: фиксированный 1.0 тс/м³ (вес кубометра воды)
            water_unit_weight = 1.0
            entries = _compute_fluid_masses(
                model        = model,
                pier         = pier,
                soil         = soil,
                z_bot        = soil.water_z_bottom,
                z_top        = soil.water_z_top,
                unit_weight  = water_unit_weight,
                gravity      = gravity,
                source       = 'вода',
                warnings     = result.warnings,
            )
            result.node_masses.extend(entries)

    # ── Масса разжиженного грунта ─────────────────────────────────────────────
    if soil.liquefaction_present:
        if soil.liquefaction_z_bottom is None or soil.liquefaction_z_top is None:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] разжижение: '
                f'liquefaction_z_bottom или liquefaction_z_top не заданы — пропускается'
            )
        elif soil.liquefaction_unit_weight is None:
            result.warnings.append(
                f'  ⚠  [{pier.pier_name}] разжижение: '
                f'liquefaction_unit_weight не задан — пропускается'
            )
        else:
            entries = _compute_fluid_masses(
                model        = model,
                pier         = pier,
                soil         = soil,
                z_bot        = soil.liquefaction_z_bottom,
                z_top        = soil.liquefaction_z_top,
                unit_weight  = soil.liquefaction_unit_weight,
                gravity      = gravity,
                source       = 'разжижение',
                warnings     = result.warnings,
            )
            result.node_masses.extend(entries)

    return result


def build_all_fluid_masses(
    piers:    list[PierGeometry],
    models:   dict[str, PierModel],           # pier_name → PierModel
    soils:    list[SoilInfluence],
    gravity:  float = 9.806,
) -> dict[str, FluidMassResult]:
    """
    Обёртка: вычисляет массы для всех опор и возвращает словарь
    pier_name → FluidMassResult.

    Параметры
    ---------
    piers   — список PierGeometry (из all_data['opory'])
    models  — словарь pier_name → PierModel (из pier_results)
    soils   — список SoilInfluence (из all_data['grunt'])
    gravity — ускорение свободного падения, м/с²
    """
    soil_by_pier: dict[str, SoilInfluence] = {s.pier_name: s for s in soils}

    results: dict[str, FluidMassResult] = {}
    for pier in piers:
        soil = soil_by_pier.get(pier.pier_name)
        if soil is None:
            fr = FluidMassResult(pier_name=pier.pier_name)
            fr.warnings.append(
                f'  ℹ  [{pier.pier_name}] нет записи в листе «Грунт» — '
                f'массы от воды и разжижения не вычисляются'
            )
            results[pier.pier_name] = fr
            continue

        if not (soil.water_mass_present or soil.liquefaction_present):
            # Нет активных источников — пропускаем без предупреждения
            results[pier.pier_name] = FluidMassResult(pier_name=pier.pier_name)
            continue

        model = models.get(pier.pier_name)
        results[pier.pier_name] = build_fluid_masses(
            pier    = pier,
            model   = model,
            soil    = soil,
            gravity = gravity,
        )

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции для агрегации (используются в mct_generator)
# ═══════════════════════════════════════════════════════════════════════════════

def aggregate_node_masses(
    entries: list[NodeMassEntry],
) -> dict[int, dict[str, float]]:
    """
    Агрегирует NodeMassEntry по node_id, суммируя массы от всех элементов.

    Возвращает dict: node_id → {'mass_x': float, 'mass_y': float, 'z': float}

    Используется в mct_generator при записи директивы *MASS в .mct файл.
    """
    aggregated: dict[int, dict[str, float]] = {}
    for entry in entries:
        nid = entry.node_id
        if nid not in aggregated:
            aggregated[nid] = {'mass_x': 0.0, 'mass_y': 0.0, 'z': entry.z}
        aggregated[nid]['mass_x'] += entry.mass_x
        aggregated[nid]['mass_y'] += entry.mass_y
    return aggregated


# ═══════════════════════════════════════════════════════════════════════════════
#  Вывод результатов в консоль
# ═══════════════════════════════════════════════════════════════════════════════

_COL_FLUID = {
    'узел':    7,
    'z, м':   10,
    'тип':    14,
    'источ.': 12,
    'mX':     16,
    'mY':     16,
}


def _fluid_tbl_header(title: str) -> str:
    sep = '─'
    widths  = list(_COL_FLUID.values())
    total_w = sum(widths) + len(widths) * 3 - 1
    headers_cells = ['Узел', 'z, м', 'Тип эл.', 'Источник',
                     'mX, тс·с²/м', 'mY, тс·с²/м']
    headers = ' | '.join(c.center(w) for c, w in zip(headers_cells, widths))
    line    = sep * total_w
    print(f'\n    {title:^{total_w}}')
    print(f'    {line}')
    print(f'    {headers}')
    print(f'    {line}')
    return line


def print_fluid_masses_report(results: dict[str, FluidMassResult]) -> None:
    """
    Выводит результаты Модуля 3 (Часть 2) в консоль в табличном виде.

    Для каждой опоры:
      — предупреждения (если есть)
      — таблица масс по узлам (детально: каждый NodeMassEntry отдельной строкой)
      — сводная строка: суммарные mX и mY

    Вызывается из main() в mct_generator.py.
    """
    for pier_name, result in results.items():
        print(f'\n  {"═" * 72}')
        print(f'  Опора [{pier_name}] — массы от воды и разжиженного грунта '
              f'(Модуль 3, Часть 2)')
        print(f'  {"═" * 72}')

        if result.warnings:
            for w in result.warnings:
                print(w)

        if not result.node_masses:
            has_active = any(
                s in (w or '') for w in result.warnings
                for s in ('вода', 'разжижение')
            )
            if not has_active:
                print('    (нет активных источников масс от воды/разжижения)')
            continue

        wf = list(_COL_FLUID.values())
        line = _fluid_tbl_header(
            'Таблица. Массы от воды и разжиженного грунта (детально по элементам)'
        )

        # Сортируем по источнику, затем по z
        for entry in sorted(result.node_masses,
                             key=lambda e: (e.source, e.z, e.node_id)):
            cells = [
                str(entry.node_id).center(wf[0]),
                f'{entry.z:.3f}'.rjust(wf[1]),
                entry.elem_type.ljust(wf[2]),
                entry.source.ljust(wf[3]),
                f'{entry.mass_x:.4f}'.rjust(wf[4]),
                f'{entry.mass_y:.4f}'.rjust(wf[5]),
            ]
            print(f'    {" | ".join(cells)}')

        print(f'    {line}')

        # ── Агрегированные итоги по узлам ────────────────────────────────────
        aggregated = aggregate_node_masses(result.node_masses)
        print(f'\n    Итого агрегировано по {len(aggregated)} узлам:')
        print(f'      Суммарная mX = {result.total_mass_x():.4f} тс·с²/м')
        print(f'      Суммарная mY = {result.total_mass_y():.4f} тс·с²/м')

        # ── Разбивка по источникам ────────────────────────────────────────────
        water_mx = sum(e.mass_x for e in result.node_masses if e.source == 'вода')
        liq_mx   = sum(e.mass_x for e in result.node_masses if e.source == 'разжижение')
        if water_mx > 0:
            print(f'        в т.ч. от воды:       mX = {water_mx:.4f} тс·с²/м')
        if liq_mx > 0:
            print(f'        в т.ч. от разжижения: mX = {liq_mx:.4f} тс·с²/м')

"""
test_module_2_part1.py — тест Части 1 Модуля 2

Запуск: python test_module_2_part1.py
"""

import math
import sys
import os

# Добавляем папку outputs в path (если запускаем из другого места)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'outputs'))
sys.path.insert(0, os.path.dirname(__file__))

from data_structures import PierGeometry, SectionZone, FrameParameters
from module_2 import generate_shaft, PierModel


# ═══════════════════════════════════════════════════════════════════════════════
#  Тестовая опора
# ═══════════════════════════════════════════════════════════════════════════════

def make_test_pier() -> PierGeometry:
    """
    Тестовая опора с двумя зонами ростверка, двумя стойки, двумя ригеля.

    Ростверк:  z = 0.00 .. 2.50 м  (2 зоны: 0..2.0, 2.0..2.5),  шаг 0.5
    Стойка:    z = 2.50 .. 11.00 м (1 зона), шаг 0.5
    Ригель:    z = 11.00 .. 12.00 м (1 зона), шаг 0.1
    """
    pier = PierGeometry(
        pier_name           = 'П1',
        geom_source         = 'parametric',
        calculate           = True,

        footing_z_top       = 2.50,
        footing_mesh_step   = 0.50,
        footing_zones       = [
            SectionZone(section_number=1, material_number=2,
                        zone_z_top=2.0, use_ts_group=False),
            SectionZone(section_number=2, material_number=2,
                        zone_z_top=2.5, use_ts_group=True, ts_group_number=10),
        ],

        column_z_top        = 11.00,
        column_mesh_step    = 0.50,
        column_zones        = [
            SectionZone(section_number=3, material_number=2,
                        zone_z_top=11.0, use_ts_group=False),
        ],

        crossbeam_z_top     = 12.00,
        crossbeam_mesh_step = 0.10,
        crossbeam_zones     = [
            SectionZone(section_number=4, material_number=2,
                        zone_z_top=12.0, use_ts_group=False),
        ],

        # Офсеты по умолчанию из PierGeometry
        node_offset_footing   = 1,
        elem_offset_footing   = 1,
        node_offset_column    = 101,
        elem_offset_column    = 101,
        node_offset_crossbeam = 201,
        elem_offset_crossbeam = 201,

        frame1 = FrameParameters(frame_number=1, x_coordinate=0.0),
    )
    return pier


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции проверки
# ═══════════════════════════════════════════════════════════════════════════════

def expected_elem_count(z_bottom: float, z_top: float, mesh_step: float) -> int:
    return max(1, math.ceil((z_top - z_bottom) / mesh_step))


def check(condition: bool, message: str) -> None:
    status = 'OK  ' if condition else 'FAIL'
    print(f'  [{status}] {message}')
    if not condition:
        global _has_failures
        _has_failures = True


_has_failures = False


# ═══════════════════════════════════════════════════════════════════════════════
#  Тесты
# ═══════════════════════════════════════════════════════════════════════════════

def test_shaft():
    global _has_failures
    _has_failures = False

    pier  = make_test_pier()
    model = generate_shaft(pier)

    print('\n─── Тест: количество элементов по зонам ───')

    # Ростверк зона 1: z=[0..2.0], шаг=0.5 → ceil(2.0/0.5)=4
    footing_z1_elems = expected_elem_count(0.0, 2.0, 0.5)   # = 4
    # Ростверк зона 2: z=[2.0..2.5], шаг=0.5 → ceil(0.5/0.5)=1
    footing_z2_elems = expected_elem_count(2.0, 2.5, 0.5)   # = 1
    footing_elems    = footing_z1_elems + footing_z2_elems   # = 5

    # Стойка зона 1: z=[2.5..11.0], шаг=0.5 → ceil(8.5/0.5)=17
    column_elems     = expected_elem_count(2.5, 11.0, 0.5)   # = 17

    # Ригель зона 1: z=[11.0..12.0], шаг=0.1 → ceil(1.0/0.1)=10
    beam_elems       = expected_elem_count(11.0, 12.0, 0.1)  # = 10

    total_elems_expected = footing_elems + column_elems + beam_elems  # = 32

    actual_elems = len(model.elements)
    check(actual_elems == total_elems_expected,
          f'Всего элементов: {actual_elems} == {total_elems_expected}')

    print('\n─── Тест: уникальность узлов (нет дублирования на стыках) ───')
    coords = [(n.x, n.y, round(n.z, 6)) for n in model.nodes.values()]
    unique_coords = set(coords)
    check(len(coords) == len(unique_coords),
          f'Все узлы уникальны: {len(unique_coords)} уникальных из {len(coords)}')

    print('\n─── Тест: стыковые узлы (footing_z_top и column_z_top не дублируются) ───')
    nodes_at_footing_top = [n for n in model.nodes.values()
                            if abs(n.z - pier.footing_z_top) < 1e-6]
    check(len(nodes_at_footing_top) == 1,
          f'Узел на z={pier.footing_z_top} (верх ростверка): 1 шт. '
          f'(найдено {len(nodes_at_footing_top)})')

    nodes_at_column_top = [n for n in model.nodes.values()
                           if abs(n.z - pier.column_z_top) < 1e-6]
    check(len(nodes_at_column_top) == 1,
          f'Узел на z={pier.column_z_top} (верх стойки): 1 шт. '
          f'(найдено {len(nodes_at_column_top)})')

    print('\n─── Тест: TS-GROUP ───')
    # Только зона 2 ростверка (1 элемент) должна попасть в группу 10
    check(10 in model.ts_groups,
          'TS-GROUP 10 существует')
    if 10 in model.ts_groups:
        check(len(model.ts_groups[10].elem_ids) == footing_z2_elems,
              f'TS-GROUP 10 содержит {footing_z2_elems} элемент(ов) '
              f'(найдено {len(model.ts_groups[10].elem_ids)})')

    print('\n─── Тест: непрерывность стержня (каждый узел_j[k] == узел_i[k+1]) ───')
    # Сортируем элементы по z нижнего узла
    elems_sorted = sorted(
        model.elements.values(),
        key=lambda e: model.nodes[e.node_i].z
    )
    continuity_ok = True
    for k in range(len(elems_sorted) - 1):
        j_node = elems_sorted[k].node_j
        i_node = elems_sorted[k + 1].node_i
        z_j = model.nodes[j_node].z
        z_i = model.nodes[i_node].z
        if abs(z_j - z_i) > 1e-6:
            continuity_ok = False
            print(f'    Разрыв: elem {elems_sorted[k].elem_id} → '
                  f'elem {elems_sorted[k+1].elem_id}, '
                  f'z_j={z_j:.4f}, z_i={z_i:.4f}')
    check(continuity_ok, 'Стержень непрерывен (нет разрывов между элементами)')

    print('\n─── Тест: нумерация офсетов ───')
    footing_node_ids = [nid for nid in model.nodes
                        if pier.node_offset_footing <= nid < pier.node_offset_column]
    column_node_ids  = [nid for nid in model.nodes
                        if pier.node_offset_column <= nid < pier.node_offset_crossbeam]
    beam_node_ids    = [nid for nid in model.nodes
                        if pier.node_offset_crossbeam <= nid < pier.node_offset_frame1]

    check(len(footing_node_ids) > 0, f'Узлы ростверка в диапазоне офсетов')
    check(len(column_node_ids) > 0,  f'Узлы стойки в диапазоне офсетов')
    check(len(beam_node_ids) > 0,    f'Узлы ригеля в диапазоне офсетов')

    # Стыковые узлы могут принадлежать предыдущей части (меньший офсет)
    total_nodes_expected = (
        (footing_z1_elems + 1)   # ростверк зона 1
        + footing_z2_elems        # ростверк зона 2 (нижний узел уже есть)
        + column_elems            # стойка (нижний узел = верх ростверка — уже есть)
        + beam_elems              # ригель (нижний узел = верх стойки — уже есть)
    )
    actual_nodes = len(model.nodes)
    check(actual_nodes == total_nodes_expected,
          f'Всего узлов: {actual_nodes} == {total_nodes_expected}')

    return not _has_failures


# ═══════════════════════════════════════════════════════════════════════════════
#  Тест с одним элементом на зону (длина < шаг)
# ═══════════════════════════════════════════════════════════════════════════════

def test_single_element_zone():
    """Зона короче шага разбивки → должен создаться ровно 1 элемент."""
    print('\n─── Тест: длина зоны < шаг → 1 элемент ───')
    pier = make_test_pier()
    # Делаем ростверк с одной зоной высотой 0.3 м при шаге 0.5 м
    pier.footing_zones = [
        SectionZone(section_number=1, material_number=2, zone_z_top=0.3)
    ]
    pier.footing_z_top      = 0.3
    pier.column_zones[0]    = SectionZone(section_number=3, material_number=2,
                                          zone_z_top=5.0)
    pier.column_z_top       = 5.0
    pier.crossbeam_zones[0] = SectionZone(section_number=4, material_number=2,
                                          zone_z_top=5.5)
    pier.crossbeam_z_top    = 5.5

    model = generate_shaft(pier)
    footing_elems = [e for e in model.elements.values()
                     if e.section_number == 1]
    check(len(footing_elems) == 1,
          f'Короткая зона (L=0.3, шаг=0.5): 1 элемент (найдено {len(footing_elems)})')


# ═══════════════════════════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('=' * 60)
    print('Тест Части 1 Модуля 2 — Стержень опоры')
    print('=' * 60)

    ok = test_shaft()
    test_single_element_zone()

    print('\n' + '=' * 60)
    if ok and not _has_failures:
        print('Все тесты прошли успешно.')
    else:
        print('Есть падения — см. выше.')
    print('=' * 60)

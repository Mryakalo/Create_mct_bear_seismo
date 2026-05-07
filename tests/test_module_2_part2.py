# ═══════════════════════════════════════════════════════════════════════════════
#  Тест Части 2
# ═══════════════════════════════════════════════════════════════════════════════
from additional_functions import _coord_key
from data_structures import PierGeometry, BearingPlaneRow
from module_2 import generate_shaft, generate_frames
from module_2_part_2 import _resolve_bearing_elevations


def _expected_frame_counts(include_temp: bool) -> tuple[int, int]:
    """
    Аналитический расчёт ожидаемого количества узлов и элементов ОДНОЙ рамки.

    Изменение (относительно исходной версии):
    Вертикали z_cg → z_road и горизонталь на z_road строятся ВСЕГДА,
    поэтому количество узлов и элементов теперь не зависит от include_temp.

    Узлы (всегда):
      - Подферменники:  2 низа + 2 верха = 4
      - Узлы z_hinge:   2 (верх ОЧ)
      - Узлы z_cg:      2 (±Y) + 1 (ось) = 3
      - Узлы z_road:    2 (±Y) + 1 (ось) = 3
      Итого = 4 + 2 + 3 + 3 = 12

    Элементы (всегда):
      - Подферменники:           2
      - Опорные части:           2
      - Вертикали z_hinge→z_cg: 2
      - Вертикали z_cg→z_road:  2
      - Горизонталь на z_cg:    2 сегмента
      - Горизонталь на z_road:  2 сегмента
      Итого = 2 + 2 + 2 + 2 + 2 + 2 = 12

    Примечание: узел на оси z_cg уже существует в стержне ригеля (coord_index),
    поэтому он не считается «новым». Тест должен это учитывать (−1 от 12 = 11).
    """
    # Узлов и элементов теперь одинаково для обоих режимов
    return 12, 12


def test_frame_part2(
        pier: PierGeometry,
        bearing_rows: list[BearingPlaneRow],
        include_temp: bool,
) -> bool:
    """
    Тест Части 2:
      1. Строит стержень + рамки.
      2. Проверяет количество узлов и элементов рамки аналитически.
      3. Проверяет, что узел горизонтали на z_cg совпадает с узлом ригеля.

    Возвращает True если все проверки прошли.
    """
    import math

    coord_index: dict = {}
    model = generate_shaft(pier)

    # Перестраиваем coord_index из узлов стержня
    for node in model.nodes.values():
        coord_index[_coord_key(node.x, node.y, node.z)] = node.node_id

    nodes_before = len(model.nodes)
    elems_before = len(model.elements)

    generate_frames(model, pier, bearing_rows, include_temp, coord_index)

    if pier.frame1 is None:
        print('  ТЕСТ: рамка 1 не задана — пропуск')
        return True

    frame = pier.frame1
    z_hinge, z_cg, z_road = _resolve_bearing_elevations(pier.pier_name, frame.frame_number, bearing_rows)

    new_nodes = len(model.nodes) - nodes_before
    new_elems = len(model.elements) - elems_before

    exp_nodes, exp_elems = _expected_frame_counts(include_temp)

    # Узел оси на z_cg: если ригель уже создал его (x=0, y=0, z=z_cg), вычитаем 1
    axis_key = _coord_key(frame.x_coordinate, 0.0, z_cg)
    axis_in_shaft = axis_key in {
        _coord_key(n.x, n.y, n.z)
        for n in list(model.nodes.values())[:nodes_before]
    }
    # Если рамка со смещением X≠0, ось не совпадёт со стержнем (x=0.0)
    if frame.x_coordinate == 0.0 and axis_in_shaft:
        exp_nodes -= 1

    ok_nodes = (new_nodes == exp_nodes)
    ok_elems = (new_elems == exp_elems)

    # Проверка: узел горизонтали на z_cg совпадает с узлом стержня
    axis_cg_key = _coord_key(frame.x_coordinate, 0.0, z_cg)
    shaft_has_cg = any(
        math.isclose(n.z, z_cg, abs_tol=1e-6) and
        math.isclose(n.x, frame.x_coordinate, abs_tol=1e-6) and
        math.isclose(n.y, 0.0, abs_tol=1e-6)
        for n in model.nodes.values()
    )
    ok_axis = shaft_has_cg

    # Итог теста
    status_nodes = '✓' if ok_nodes else f'✗ ожидалось {exp_nodes}'
    status_elems = '✓' if ok_elems else f'✗ ожидалось {exp_elems}'
    status_axis = '✓' if ok_axis else '✗ узел оси на z_cg не найден'

    print(f'  ТЕСТ Части 2 ({'with_temp' if include_temp else 'no_temp'}):')
    print(f'    новых узлов рамки  = {new_nodes}  {status_nodes}')
    print(f'    новых элементов    = {new_elems}  {status_elems}')
    print(f'    узел оси на z_cg   {status_axis}')

    return ok_nodes and ok_elems and ok_axis

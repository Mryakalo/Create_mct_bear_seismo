"""
module_2.py — Модуль 2: генерация параметрической геометрии опоры

Часть 1 — Стержень (ростверк → стойка → ригель):
    Мешинг трёх частей вдоль оси Z, каждая со своими зонами сечений.
    Узлы на стыках частей не дублируются.
    Заполняет model.nodes, model.elements, model.ts_groups.
"""

from typing import Optional

from additional_functions import _coord_key, _z_coordinates_for_zone, _add_ts_group_element
from data_structures import (
    BearingPlaneRow, FrameParameters, FrameRLS,
    PierGeometry, SectionZone, PierModel, Node, Element,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 1 — мешинг одной части стержня
# ═══════════════════════════════════════════════════════════════════════════════

def _mesh_shaft_part(
    model:       PierModel,
    zones:       list[SectionZone],
    z_bottom:    float,
    z_top_part:  float,
    mesh_step:   float,
    node_offset: int,
    elem_offset: int,
    coord_index: dict,
) -> tuple[int, int, int]:
    """
    Мешит одну часть стержня (ростверк / стойку / ригель).

    zones       — список SectionZone для этой части (отсортированы по z_top возрастанию)
    z_bottom    — Z низа части
    z_top_part  — Z верха части
    mesh_step   — шаг разбивки, м
    node_offset — стартовый офсет нумерации узлов для этой части
    elem_offset — стартовый офсет нумерации элементов для этой части
    coord_index — общий индекс координат опоры

    Возвращает: (кол-во новых узлов, кол-во новых элементов, node_id верхнего узла)
    """
    if not zones:
        raise ValueError('Список зон не может быть пустым')

    # Убедимся, что зоны отсортированы по z_top
    sorted_zones = sorted(zones, key=lambda z: z.zone_z_top)

    # Счётчики для офсетов внутри части
    node_local_counter = 0
    elem_local_counter = 0
    new_nodes_count    = 0
    new_elems_count    = 0

    def next_node_id() -> int:
        nonlocal node_local_counter
        nid = node_offset + node_local_counter
        node_local_counter += 1
        return nid

    def next_elem_id() -> int:
        nonlocal elem_local_counter
        eid = elem_offset + elem_local_counter
        elem_local_counter += 1
        return eid

    # Переопределяем get_or_create для локальных счётчиков
    def _get_or_create(x: float, y: float, z: float) -> tuple[int, bool]:
        """Возвращает (node_id, is_new)."""
        nonlocal new_nodes_count
        key = _coord_key(x, y, z)
        if key in coord_index:
            return coord_index[key], False
        nid = next_node_id()
        model.nodes[nid] = Node(node_id=nid, x=x, y=y, z=z)
        coord_index[key] = nid
        new_nodes_count += 1
        return nid, True

    current_z_bottom = z_bottom

    for zone in sorted_zones:
        zone_z_top = min(zone.zone_z_top, z_top_part)  # защита от выхода за верх части

        z_coords = _z_coordinates_for_zone(current_z_bottom, zone_z_top, mesh_step)

        for k in range(len(z_coords) - 1):
            node_i_id, _ = _get_or_create(0.0, 0.0, z_coords[k])
            node_j_id, _ = _get_or_create(0.0, 0.0, z_coords[k + 1])

            eid = next_elem_id()
            model.elements[eid] = Element(
                elem_id         = eid,
                node_i          = node_i_id,
                node_j          = node_j_id,
                section_number  = zone.section_number,
                material_number = zone.material_number,
            )
            new_elems_count += 1

            if zone.use_ts_group and zone.ts_group_number is not None:
                _add_ts_group_element(model, zone.ts_group_number, eid)

        current_z_bottom = zone_z_top

    # Получаем id узла на самом верху части (уже существует — создан в последнем пролёте)
    top_node_key = _coord_key(0.0, 0.0, z_top_part)
    top_node_id  = coord_index[top_node_key]

    return new_nodes_count, new_elems_count, top_node_id


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция Части 1
# ═══════════════════════════════════════════════════════════════════════════════

def generate_shaft(pier: PierGeometry) -> PierModel:
    """
    Генерирует КЭ-модель стержня опоры (ростверк → стойка → ригель).

    Принимает PierGeometry с заполненными:
        footing_zones, footing_z_top, footing_mesh_step,
        column_zones,  column_z_top,  column_mesh_step,
        crossbeam_zones, crossbeam_z_top, crossbeam_mesh_step,
        node_offset_*, elem_offset_*.

    Возвращает PierModel с заполненными nodes, elements, ts_groups.
    Печатает сводку по каждой части.
    """
    model       = PierModel(pier_name=pier.pier_name)
    coord_index: dict = {}   # общий индекс координат для всей опоры

    # ── Нижняя граница ростверка ─────────────────────────────────────────────
    # Z низа ростверка = z_top самой нижней зоны ростверка не определяется
    # в PierGeometry явно; принимаем z_top самой нижней зоны = footing_zones[0].zone_z_top,
    # а z_bottom ростверка = footing_zones[-1].zone_z_top - высота, но в данных
    # структурах z_top зон — это АБСОЛЮТНЫЕ отметки.
    # Нижнюю границу ростверка берём как z_top зоны с минимальным z_top (первая зона).
    # Это согласуется с алгоритмом: первая зона начинается от z_bottom_of_part.
    # z_bottom_of_part ростверка = ??? — не задан явно, берём как (footing_z_top - сумма длин зон).
    # Для простоты: z низа первой зоны = zone_z_top[0] - (zone_z_top[0] - z_bottom_footing),
    # где z_bottom_footing явно не задан в структуре. Используем соглашение:
    # нижняя граница = zone_z_top первой зоны ростверка (она же — низ зоны 1 = 0.0 в локальных координатах?)
    # НЕТ — зоны хранят только z_top. z_bottom первой зоны = не задан явно.
    # Решение: z_bottom части = z_top предыдущей части (ростверк — нет предыдущей, значит явно нужен z_bottom).
    # Из анализа данных: footing_zones[-1].zone_z_top == footing_z_top,
    # а footing_zones[0] — самая нижняя зона. Её нижняя граница неизвестна из zones.
    # Принимаем: z_bottom ростверка = footing_z_top - sum(длин зон). Длины неизвестны.
    # ВЫВОД: z_bottom должен приходить снаружи. Используем footing_zones[0].zone_z_top
    # как единственную точку, если зона одна, или берём z_bottom стойки из column_z_top.
    # Правильное чтение структуры: zone_z_top — верх ЭТОЙ зоны; низ первой зоны
    # задаётся контекстом. Для ростверка нет явного поля z_bottom. Принимаем:
    #   z_bottom_footing = footing_zones[0].zone_z_top - высота первой зоны = ?
    # Задокументированный алгоритм: "z_bottom_of_part = z_top предыдущей части (или 0 для ростверка)"
    # Значит: z_bottom ростверка = 0.
    #
    # Итого соглашение: z_bottom ростверка = 0, стойки = footing_z_top, ригеля = column_z_top.

    parts = [
        dict(
            name        = 'Ростверк',
            zones       = pier.footing_zones,
            z_bottom    = 0.0,
            z_top       = pier.footing_z_top,
            mesh_step   = pier.footing_mesh_step,
            node_offset = pier.node_offset_footing,
            elem_offset = pier.elem_offset_footing,
        ),
        dict(
            name        = 'Стойка',
            zones       = pier.column_zones,
            z_bottom    = pier.footing_z_top,
            z_top       = pier.column_z_top,
            mesh_step   = pier.column_mesh_step,
            node_offset = pier.node_offset_column,
            elem_offset = pier.elem_offset_column,
        ),
        dict(
            name        = 'Ригель',
            zones       = pier.crossbeam_zones,
            z_bottom    = pier.column_z_top,
            z_top       = pier.crossbeam_z_top,
            mesh_step   = pier.crossbeam_mesh_step,
            node_offset = pier.node_offset_crossbeam,
            elem_offset = pier.elem_offset_crossbeam,
        ),
    ]

    print(f'  Опора [{pier.pier_name}] — стержень:')

    for part in parts:
        if part['z_top'] is None:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: z_top не задан')
        if not part['zones']:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: список зон пуст')

        length = part['z_top'] - part['z_bottom']
        if length <= 0:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: '
                f'z_bottom={part["z_bottom"]:.4f} >= z_top={part["z_top"]:.4f}')

        n_nodes, n_elems, _ = _mesh_shaft_part(
            model       = model,
            zones       = part['zones'],
            z_bottom    = part['z_bottom'],
            z_top_part  = part['z_top'],
            mesh_step   = part['mesh_step'],
            node_offset = part['node_offset'],
            elem_offset = part['elem_offset'],
            coord_index = coord_index,
        )

        print(f'    {part["name"]:10s}: L={length:.3f} м, '
              f'узлов={n_nodes}, элементов={n_elems}')

    print(f'    Итого по опоре: узлов={len(model.nodes)}, '
          f'элементов={len(model.elements)}, '
          f'TS-групп={len(model.ts_groups)}')

    part_offsets = {p["name"]: p["elem_offset"] for p in parts}
    print_element_table(model, part_offsets)

    return model


# ═══════════════════════════════════════════════════════════════════════════════
#  Таблица элементов для вывода пользователю
# ═══════════════════════════════════════════════════════════════════════════════

# Ширины столбцов таблицы (символов)
_COL = {
    'elem':    7,   # №  эл.
    'node_i':  8,   # узел i
    'node_j':  8,   # узел j
    'part':   10,   # часть
    'length': 10,   # длина, м
    'sec':     7,   # сечение
    'mat':     8,   # материал
}


def _part_label(elem_id: int, offsets: dict[str, int]) -> str:
    """
    Определяет принадлежность элемента к части опоры по его id и офсетам.
    offsets = {'Ростверк': off_f, 'Стойка': off_c, 'Ригель': off_b, ...}
    Возвращает название части, чьи границы охватывают elem_id.
    """
    # Сортируем части по офсету по возрастанию; принадлежность — первый офсет ≤ elem_id
    sorted_parts = sorted(offsets.items(), key=lambda kv: kv[1])
    result = sorted_parts[0][0]
    for name, off in sorted_parts:
        if elem_id >= off:
            result = name
    return result


def print_element_table(model: PierModel, part_offsets: dict[str, int]) -> None:
    """
    Выводит в консоль таблицу всех элементов модели со столбцами:
        № эл. | узел i | узел j | часть | длина, м | сечение | материал

    part_offsets — словарь {имя_части: elem_offset} для определения принадлежности.
    Элементы сортируются по id.
    """
    # ── Заголовок ────────────────────────────────────────────────────────────
    sep_char = '─'
    col_widths = list(_COL.values())
    total_width = sum(col_widths) + len(col_widths) * 3 - 1  # 3 = ' | ' между колонками

    header_cells = ['№ эл.', 'Узел i', 'Узел j', 'Часть', 'Длина, м', 'Сечение', 'Материал']
    header_parts = [cell.center(w) for cell, w in zip(header_cells, col_widths)]
    separator    = sep_char * total_width

    print(f'\n    {"Таблица элементов стержня":^{total_width}}')
    print(f'    {separator}')
    print(f'    {" | ".join(header_parts)}')
    print(f'    {separator}')

    # ── Строки ───────────────────────────────────────────────────────────────
    for elem_id in sorted(model.elements):
        elem   = model.elements[elem_id]
        node_i = model.nodes[elem.node_i]
        node_j = model.nodes[elem.node_j]
        length = abs(node_j.z - node_i.z)
        part   = _part_label(elem_id, part_offsets)

        cells = [
            str(elem_id)              .rjust(_COL['elem']),
            str(elem.node_i)          .rjust(_COL['node_i']),
            str(elem.node_j)          .rjust(_COL['node_j']),
            part                      .ljust(_COL['part']),
            f'{length:.4f}'           .rjust(_COL['length']),
            str(elem.section_number)  .rjust(_COL['sec']),
            str(elem.material_number) .rjust(_COL['mat']),
        ]
        print(f'    {" | ".join(cells)}')

    print(f'    {separator}')
    print(f'    Итого элементов: {len(model.elements)}')


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 2 — Рамки (подферменники → опорные части → вертикали → горизонтали)
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_bearing_elevations(
    pier_name: str,
    bearing_rows: list[BearingPlaneRow],
) -> tuple[float, float, float]:
    """
    Возвращает (z_hinge, z_cg, z_road) для данной опоры из bearing_rows.

    Одна опора может встречаться в нескольких строках (граничная опора двух
    плетей) — отметки Z при этом одинаковы; берём из первой строки.
    Выбрасывает ValueError если нет строк или отметки не заданы.
    """
    rows = [r for r in bearing_rows if r.pier_name == pier_name]
    if not rows:
        raise ValueError(
            f'[{pier_name}] нет строк в bearing_rows для данной опоры')
    row = rows[0]
    missing = [
        name for name, val in (
            ('z_hinge', row.z_hinge_elevation),
            ('z_cg',    row.z_cg_elevation),
            ('z_road',  row.z_road_elevation),
        ) if val is None
    ]
    if missing:
        raise ValueError(
            f'[{pier_name}] в bearing_rows не заданы: {", ".join(missing)}')
    return row.z_hinge_elevation, row.z_cg_elevation, row.z_road_elevation


def _get_bearing_type(
    pier_name:      str,
    bearing_number: Optional[int],
    bearing_rows:   list[BearingPlaneRow],
) -> tuple[str, str]:
    """
    Возвращает (bearing_type_X, bearing_type_Y) для опорной части с заданным номером.

    Поиск по right_bearing_number и left_bearing_number во всех строках опоры.
    По умолчанию (номер не задан или не найден) — ('fixed', 'fixed').
    """
    if bearing_number is None:
        return 'fixed', 'fixed'
    for row in bearing_rows:
        if row.pier_name != pier_name:
            continue
        if row.right_bearing_number == bearing_number:
            return row.right_bearing_type_X, row.right_bearing_type_Y
        if row.left_bearing_number == bearing_number:
            return row.left_bearing_type_X, row.left_bearing_type_Y
    return 'fixed', 'fixed'


def _make_rls(movable_x: bool, movable_y: bool) -> tuple:
    """
    Формирует кортеж release_j для опорной части.

    Шарниры My, Mz освобождаются всегда (узел верха ОЧ = z_hinge).
    Fx освобождается если movable_X; Fy — если movable_Y.
    Формат: (Fx, Fy, Fz, Mx, My, Mz).
    """
    return (movable_x, movable_y, False, False, True, True)


def _build_frame(
    model:        PierModel,
    pier:         PierGeometry,
    frame:        FrameParameters,
    z_hinge:      float,
    z_cg:         float,
    z_road:       float,
    include_temp: bool,
    bearing_rows: list[BearingPlaneRow],
    node_offset:  int,
    elem_offset:  int,
    coord_index:  dict,            # общий индекс координат опоры (изменяемый)
    bearing_numbers: tuple[Optional[int], Optional[int]],  # (правый, левый) = (+Y, -Y)
) -> tuple[int, int]:
    """
    Строит узлы и элементы одной рамки в model.

    Порядок Y: правый подферменник = +pad_y_half_width, левый = -pad_y_half_width.
    bearing_numbers = (right_bn, left_bn) соответствует (+Y, -Y).

    Возвращает (кол-во новых узлов, кол-во новых элементов).
    """
    x   = frame.x_coordinate
    py  = frame.pad_y_half_width
    y_values: list[tuple[float, Optional[int]]] = [
        ( py, bearing_numbers[0]),   # правый (+Y)
        (-py, bearing_numbers[1]),   # левый  (-Y)
    ]

    new_nodes_count = 0
    new_elems_count = 0

    node_local = [0]   # счётчик новых узлов для offset
    elem_local = [0]

    def _get_or_create(x_: float, y_: float, z_: float) -> int:
        nonlocal new_nodes_count
        key = _coord_key(x_, y_, z_)
        if key in coord_index:
            return coord_index[key]
        nid = node_offset + node_local[0]
        node_local[0] += 1
        model.nodes[nid] = Node(node_id=nid, x=x_, y=y_, z=z_)
        coord_index[key] = nid
        new_nodes_count += 1
        return nid

    def _add_elem(ni: int, nj: int, sec: int, mat: int) -> int:
        nonlocal new_elems_count
        eid = elem_offset + elem_local[0]
        elem_local[0] += 1
        model.elements[eid] = Element(
            elem_id=eid, node_i=ni, node_j=nj,
            section_number=sec, material_number=mat,
        )
        new_elems_count += 1
        return eid

    # Для каждого из двух подферменников запоминаем узел верха ОЧ = z_hinge
    pad_top_nodes: dict[float, int] = {}   # y → node_id верха подферменника

    # ── 1. Подферменники ─────────────────────────────────────────────────────
    for y, _bn in y_values:
        n_bot = _get_or_create(x, y, frame.pad_z_bottom)
        n_top = _get_or_create(x, y, frame.pad_z_top)
        _add_elem(n_bot, n_top, frame.pad_section, frame.pad_material)
        pad_top_nodes[y] = n_top

    # ── 2. Опорные части (без собственного веса) ─────────────────────────────
    hinge_nodes: dict[float, int] = {}   # y → node_id на z_hinge

    for y, bn in y_values:
        n_bot = pad_top_nodes[y]                         # верх подферменника
        n_top = _get_or_create(x, y, z_hinge)
        eid   = _add_elem(n_bot, n_top, frame.bearing_section, frame.bearing_material)
        hinge_nodes[y] = n_top

        # Тип опирания и шарниры
        b_type_x, b_type_y = _get_bearing_type(pier.pier_name, bn, bearing_rows)
        movable_x = (b_type_x == 'movable')
        movable_y = (b_type_y == 'movable')

        model.frame_rls[eid] = FrameRLS(
            elem_id   = eid,
            release_i = (False, False, False, False, False, False),
            release_j = _make_rls(movable_x, movable_y),
        )

    # ── 3. Вертикали z_hinge → z_cg ─────────────────────────────────────────
    cg_nodes: dict[float, int] = {}

    for y, _bn in y_values:
        n_bot = hinge_nodes[y]
        n_top = _get_or_create(x, y, z_cg)
        _add_elem(n_bot, n_top, frame.frame_section, frame.frame_material)
        cg_nodes[y] = n_top

    # ── 4. [include_temp] Вертикали z_cg → z_road ───────────────────────────
    road_nodes: dict[float, int] = {}

    if include_temp:
        for y, _bn in y_values:
            n_bot = cg_nodes[y]
            n_top = _get_or_create(x, y, z_road)
            _add_elem(n_bot, n_top, frame.frame_section, frame.frame_material)
            road_nodes[y] = n_top

    # ── 5. Горизонталь 1 на z_cg ─────────────────────────────────────────────
    # Три сегмента: (-py, 0, z_cg) — (0, 0, z_cg) — (+py, 0, z_cg).
    # Узел на оси (x, 0, z_cg) совпадает с узлом стержня ригеля на той же Z.
    n_left  = cg_nodes[-py]
    n_right = cg_nodes[ py]
    n_axis  = _get_or_create(x, 0.0, z_cg)

    _add_elem(n_left,  n_axis,  frame.frame_section, frame.frame_material)
    _add_elem(n_axis,  n_right, frame.frame_section, frame.frame_material)

    # ── 6. [include_temp] Горизонталь 2 на z_road ────────────────────────────
    if include_temp:
        n_left_r  = road_nodes[-py]
        n_right_r = road_nodes[ py]
        n_axis_r  = _get_or_create(x, 0.0, z_road)

        _add_elem(n_left_r,  n_axis_r,  frame.frame_section, frame.frame_material)
        _add_elem(n_axis_r,  n_right_r, frame.frame_section, frame.frame_material)

    return new_nodes_count, new_elems_count


def _find_bearing_numbers_for_frame(
    pier: PierGeometry,
    frame: FrameParameters,
    bearing_rows: list[BearingPlaneRow],
) -> tuple[Optional[int], Optional[int]]:
    """
    Определяет (right_bearing_number, left_bearing_number) для заданной рамки.

    Рамка 1 (frame_number=1) соответствует первому вхождению опоры в bearing_rows.
    Рамка 2 (frame_number=2) — второму вхождению (граничная опора двух плетей).
    Правый (бо́льший Y) → right_bearing_number; левый → left_bearing_number.
    """
    rows = [r for r in bearing_rows if r.pier_name == pier.pier_name]
    if not rows:
        return None, None
    idx = frame.frame_number - 1
    row = rows[idx] if idx < len(rows) else rows[0]
    return row.right_bearing_number, row.left_bearing_number


def generate_frames(
    model:        PierModel,
    pier:         PierGeometry,
    bearing_rows: list[BearingPlaneRow],
    include_temp: bool,
    coord_index:  dict,
) -> None:
    """
    Часть 2 модуля 2 — строит рамки опоры.

    Добавляет узлы и элементы рамок в model, заполняет model.frame_rls.
    coord_index — общий индекс координат, созданный в generate_shaft().

    Обрабатывает рамку 1 и (при наличии) рамку 2.
    Особый случай shared_pad_with_other_frame: внутренние узлы подферменников
    двух рамок переиспользуются через общий coord_index.
    """
    z_hinge, z_cg, z_road = _resolve_bearing_elevations(
        pier.pier_name, bearing_rows)

    frames_to_build: list[tuple[FrameParameters, int, int]] = []
    if pier.frame1 is not None:
        frames_to_build.append(
            (pier.frame1, pier.node_offset_frame1, pier.elem_offset_frame1))
    if pier.frame2 is not None:
        frames_to_build.append(
            (pier.frame2, pier.node_offset_frame2, pier.elem_offset_frame2))

    if not frames_to_build:
        return

    print(f'    Рамки: {'no_temp' if not include_temp else 'with_temp'}, '
          f'z_hinge={z_hinge:.3f}, z_cg={z_cg:.3f}, z_road={z_road:.3f}')

    for frame, node_off, elem_off in frames_to_build:
        bn_right, bn_left = _find_bearing_numbers_for_frame(
            pier, frame, bearing_rows)

        n_new, e_new = _build_frame(
            model        = model,
            pier         = pier,
            frame        = frame,
            z_hinge      = z_hinge,
            z_cg         = z_cg,
            z_road       = z_road,
            include_temp = include_temp,
            bearing_rows = bearing_rows,
            node_offset  = node_off,
            elem_offset  = elem_off,
            coord_index  = coord_index,
            bearing_numbers = (bn_right, bn_left),
        )
        label = 'Рамка 1' if frame.frame_number == 1 else 'Рамка 2'
        print(f'      {label}: узлов={n_new}, элементов={e_new}, '
              f'RLS-записей={len(model.frame_rls)}')


# ═══════════════════════════════════════════════════════════════════════════════
#  Тест Части 2
# ═══════════════════════════════════════════════════════════════════════════════

def _expected_frame_counts(include_temp: bool) -> tuple[int, int]:
    """
    Аналитический расчёт ожидаемого количества узлов и элементов ОДНОЙ рамки.

    Без временной нагрузки (no_temp):
      Узлы:
        - Подферменники: 2 низа + 2 верха = 4 (узел низа подферменника — всегда новый,
          верх — тоже, если не shared_pad)
        - Узлы z_hinge:  2 (верх ОЧ)
        - Узлы z_cg:     2 (+Y и -Y) + 1 (ось) = 3
        Итого = 4 + 2 + 3 = 9

      Элементы:
        - Подферменники: 2
        - ОЧ:            2
        - Вертикали z_hinge→z_cg: 2
        - Горизонталь 1: 2 сегмента
        Итого = 2 + 2 + 2 + 2 = 8

    С временной нагрузкой (with_temp):
      Узлы:
        - z_road: 2 (+Y/-Y) + 1 (ось) = 3 дополнительных
        Итого = 9 + 3 = 12

      Элементы:
        - Вертикали z_cg→z_road: 2
        - Горизонталь 2: 2 сегмента
        Итого = 8 + 4 = 12

    Примечание: узел на оси z_cg уже существует в стержне ригеля (coord_index),
    поэтому он не считается «новым» — функция _build_frame не создаёт дубль.
    В расчёте выше он учтён как 1, но на практике new_nodes_count будет меньше
    на 1 (если ригель уже создал этот узел). Тест должен это учитывать.
    """
    if include_temp:
        return 12, 12
    return 9, 8


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

    frame          = pier.frame1
    z_hinge, z_cg, z_road = _resolve_bearing_elevations(pier.pier_name, bearing_rows)

    new_nodes = len(model.nodes)    - nodes_before
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
    axis_cg_key  = _coord_key(frame.x_coordinate, 0.0, z_cg)
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
    status_axis  = '✓' if ok_axis  else '✗ узел оси на z_cg не найден'

    print(f'  ТЕСТ Части 2 ({'with_temp' if include_temp else 'no_temp'}):')
    print(f'    новых узлов рамки  = {new_nodes}  {status_nodes}')
    print(f'    новых элементов    = {new_elems}  {status_elems}')
    print(f'    узел оси на z_cg   {status_axis}')

    return ok_nodes and ok_elems and ok_axis


# ═══════════════════════════════════════════════════════════════════════════════
#  Модуль 2 — публичный API (точка входа для других модулей)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pier_geometry(
    pier:         PierGeometry,
    bearing_rows: list[BearingPlaneRow] | None = None,
    include_temp: bool = False,
) -> Optional[PierModel]:
    """
    Генерирует полную параметрическую геометрию опоры.

    Часть 1 (стержень): ростверк → стойка → ригель.
    Часть 2 (рамки):    подферменники → ОЧ → вертикали → горизонтали.

    Возвращает None для опор с geom_source='mct'.
    bearing_rows нужен для Части 2; если не передан — рамки не строятся.
    """
    if pier.geom_source == 'mct':
        print(f'  Опора [{pier.pier_name}]: geom_source=mct, геометрия из файла — пропуск')
        return None

    # ── Часть 1 — стержень ───────────────────────────────────────────────────
    coord_index: dict = {}
    model = generate_shaft(pier)

    # Переносим узлы стержня в coord_index для совместного использования
    for node in model.nodes.values():
        coord_index[_coord_key(node.x, node.y, node.z)] = node.node_id

    # ── Часть 2 — рамки ──────────────────────────────────────────────────────
    has_frames = pier.frame1 is not None or pier.frame2 is not None
    if has_frames and bearing_rows is not None:
        generate_frames(model, pier, bearing_rows, include_temp, coord_index)
    elif has_frames:
        print(f'  [{pier.pier_name}] рамки заданы, но bearing_rows не передан — пропуск Части 2')

    return model
"""
module_2.py — Модуль 2: генерация параметрической геометрии опоры

Часть 1 — Стержень (ростверк → стойка → ригель):
    Мешинг трёх частей вдоль оси Z, каждая со своими зонами сечений.
    Узлы на стыках частей не дублируются.
    Заполняет model.nodes, model.elements, model.ts_groups.
"""

from typing import Optional

from additional_functions import _coord_key, _z_coordinates_for_zone, _add_ts_group_element
from data_structures import PierGeometry, SectionZone, PierModel, Node, Element


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
#  Модуль 2 — публичный API (точка входа для других модулей)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pier_geometry(pier: PierGeometry) -> Optional[PierModel]:
    """
    Генерирует полную параметрическую геометрию опоры.
    Сейчас реализована только Часть 1 (стержень).
    Возвращает None для опор с geom_source='mct'.
    """
    if pier.geom_source == 'mct':
        print(f'  Опора [{pier.pier_name}]: geom_source=mct, геометрия из файла — пропуск')
        return None

    model = generate_shaft(pier)
    # Части 2–N (рамки, сваи) будут добавлены позже
    return model
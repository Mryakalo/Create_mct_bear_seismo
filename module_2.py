"""
module_2.py — Модуль 2: генерация параметрической геометрии опоры

Часть 1 — Стержень (ростверк → стойка → ригель):
    Мешинг трёх частей вдоль оси Z, каждая со своими зонами сечений.
    Узлы на стыках частей не дублируются.
    Заполняет model.nodes, model.elements, model.ts_groups.
"""

from dataclasses import dataclass, field
from typing import Optional

from additional_functions import _coord_key, _z_coordinates_for_zone, _add_ts_group_element
from data_structures import (
    BearingPlaneRow, FrameParameters, FrameRLS,
    PierGeometry, SectionZone, PierModel, Node, Element,
)
from module_2_part3 import (
    load_piles_for_pier, load_pier_body_for_pier,
    PileLoadResult, MctLoadResult,
)


# ── Несимметричные подферменники ─────────────────────────────────────────────
# module_1.parse_frame_parameters читает из листа «Опоры»:
#   f{n}_r_pad_y → FrameParameters.pad_y_right  (+Y, правый подферменник)
#   f{n}_l_pad_y → FrameParameters.pad_y_left   (−Y, левый  подферменник, >0)
# Если колонки не заданы — оба равны f{n}_pad_y (симметричный режим).
# data_structures.FrameParameters должен содержать поля pad_y_right и pad_y_left.
# ─────────────────────────────────────────────────────────────────────────────


# ── Результирующие структуры для вывода (используются в main) ─────────────────

@dataclass
class ShaftPartResult:
    """Итог мешинга одной части стержня (для вывода в main)."""
    name: str
    z_bottom: float
    z_top: float
    n_nodes: int
    n_elems: int
    elem_offset: int


@dataclass
class BearingMeta:
    """Метаданные одной опорной части (для вывода в main)."""
    side: str  # 'правая (+Y)' / 'левая (−Y)'
    bn: Optional[int]
    x: float
    y: float
    z_bot: float  # z верха подферменника
    z_top: float  # z_hinge
    height: float
    type_x: str  # fixed / movable
    type_y: str


@dataclass
class FrameResult:
    """Итог построения одной рамки (для вывода в main)."""
    frame_number: int
    x_coordinate: float
    pad_z_bottom: float
    pad_z_top: float
    pad_y_half_width: float  # оставлено для обратной совместимости (среднее или симм. значение)
    pad_y_right: float  # Y правого подферменника (+Y сторона)
    pad_y_left: float  # Y левого подферменника  (−Y сторона, хранится как положительное)
    pad_section: int
    pad_material: int
    bearing_section: int
    bearing_material: int
    frame_section: int
    frame_material: int
    z_hinge: float
    z_cg: float
    z_road: float
    include_temp: bool
    n_nodes: int
    n_elems: int
    bearing_metas: list[BearingMeta]
    elem_labels: list[tuple[int, str]]  # [(elem_id, sublabel), ...]


@dataclass
class PierGeometryResult:
    """Полный итог generate_pier_geometry (для вывода в main)."""
    pier_name: str
    model: Optional[PierModel]
    shaft_parts: list[ShaftPartResult] = field(default_factory=list)
    frame_results: list[FrameResult] = field(default_factory=list)
    # Результат загрузки из .mct (заполняется только если geom_source='mct')
    mct_body_result: Optional[MctLoadResult] = None
    # Результат загрузки свай из .mct (заполняется если задан pile_mct_file_path)
    pile_result: Optional[PileLoadResult] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 1 — мешинг одной части стержня
# ═══════════════════════════════════════════════════════════════════════════════

def _mesh_shaft_part(
        model: PierModel,
        zones: list[SectionZone],
        z_bottom: float,
        z_top_part: float,
        mesh_step: float,
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
    new_nodes_count = 0
    new_elems_count = 0

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
                elem_id=eid,
                node_i=node_i_id,
                node_j=node_j_id,
                section_number=zone.section_number,
                material_number=zone.material_number,
            )
            new_elems_count += 1

            if zone.use_ts_group and zone.ts_group_number is not None:
                _add_ts_group_element(model, zone.ts_group_number, eid)

        current_z_bottom = zone_z_top

    # Получаем id узла на самом верху части (уже существует — создан в последнем пролёте)
    top_node_key = _coord_key(0.0, 0.0, z_top_part)
    top_node_id = coord_index[top_node_key]

    return new_nodes_count, new_elems_count, top_node_id


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция Части 1
# ═══════════════════════════════════════════════════════════════════════════════

def generate_shaft(pier: PierGeometry) -> tuple[PierModel, list[ShaftPartResult]]:
    """
    Генерирует КЭ-модель стержня опоры (ростверк → стойка → ригель).

    Принимает PierGeometry с заполненными:
        footing_zones, footing_z_top, footing_mesh_step,
        column_zones,  column_z_top,  column_mesh_step,
        crossbeam_zones, crossbeam_z_top, crossbeam_mesh_step,
        node_offset_*, elem_offset_*.

    Возвращает (PierModel, list[ShaftPartResult]).
    Не печатает ничего — вывод делает main через print_shaft_report().
    """
    model = PierModel(pier_name=pier.pier_name)
    coord_index: dict = {}  # общий индекс координат для всей опоры
    shaft_results: list[ShaftPartResult] = []

    # ── Нижняя граница ростверка ─────────────────────────────────────────────

    parts = [
        dict(
            name='Ростверк',
            zones=pier.footing_zones,
            z_bottom=0.0,
            z_top=pier.footing_z_top,
            mesh_step=pier.footing_mesh_step,
            node_offset=pier.node_offset_footing,
            elem_offset=pier.elem_offset_footing,
        ),
        dict(
            name='Стойка',
            zones=pier.column_zones,
            z_bottom=pier.footing_z_top,
            z_top=pier.column_z_top,
            mesh_step=pier.column_mesh_step,
            node_offset=pier.node_offset_column,
            elem_offset=pier.elem_offset_column,
        ),
        dict(
            name='Ригель',
            zones=pier.crossbeam_zones,
            z_bottom=pier.column_z_top,
            z_top=pier.crossbeam_z_top,
            mesh_step=pier.crossbeam_mesh_step,
            node_offset=pier.node_offset_crossbeam,
            elem_offset=pier.elem_offset_crossbeam,
        ),
    ]

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
            model=model,
            zones=part['zones'],
            z_bottom=part['z_bottom'],
            z_top_part=part['z_top'],
            mesh_step=part['mesh_step'],
            node_offset=part['node_offset'],
            elem_offset=part['elem_offset'],
            coord_index=coord_index,
        )

        shaft_results.append(ShaftPartResult(
            name=part['name'],
            z_bottom=part['z_bottom'],
            z_top=part['z_top'],
            n_nodes=n_nodes,
            n_elems=n_elems,
            elem_offset=part['elem_offset'],
        ))

    return model, shaft_results


# ── Таблица элементов стержня и рамок ─────────────────────────────────────────
# Функции форматирования вынесены в mct_generator.py (print_shaft_report,
# print_frames_report). Здесь только вспомогательная утилита для определения
# принадлежности элемента по elem_id и словарю офсетов.

def _part_label(elem_id: int, offsets: dict[str, int]) -> str:
    """
    Определяет принадлежность элемента к части опоры по его id и офсетам.
    offsets = {'Ростверк': off_f, 'Стойка': off_c, 'Ригель': off_b, ...}
    Возвращает название части, чьи границы охватывают elem_id.
    """
    sorted_parts = sorted(offsets.items(), key=lambda kv: kv[1])
    result = sorted_parts[0][0]
    for name, off in sorted_parts:
        if elem_id >= off:
            result = name
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 2 — Рамки (подферменники → опорные части → вертикали → горизонтали)
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_bearing_elevations(
        pier_name: str,
        frame_number: int,
        bearing_rows: list[BearingPlaneRow],
) -> tuple[float, float, float]:
    """
    Возвращает (z_hinge, z_cg, z_road) для конкретной рамки опоры.

    Рамка N соответствует N-му вхождению опоры в bearing_rows (по порядку).
    Для граничной опоры двух плетей значения Z могут различаться между рамками.
    Выбрасывает ValueError если нет нужной строки или отметки не заданы.
    """
    rows = [r for r in bearing_rows if r.pier_name == pier_name]
    if not rows:
        raise ValueError(
            f'[{pier_name}] нет строк в bearing_rows для данной опоры')

    idx = frame_number - 1
    if idx >= len(rows):
        raise ValueError(
            f'[{pier_name}] рамка {frame_number} запрошена, '
            f'но в листе "Плеть" только {len(rows)} вхождений для этой опоры.')
    row = rows[idx]

    missing = [
        name for name, val in (
            ('z_hinge', row.z_hinge_elevation),
            ('z_cg', row.z_cg_elevation),
            ('z_road', row.z_road_elevation),
        ) if val is None
    ]
    if missing:
        raise ValueError(
            f'[{pier_name}] рамка {frame_number}: в bearing_rows не заданы: '
            f'{", ".join(missing)}')

    return row.z_hinge_elevation, row.z_cg_elevation, row.z_road_elevation


def _get_bearing_type(
        pier_name: str,
        bearing_number: Optional[int],
        bearing_rows: list[BearingPlaneRow],
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


# Тип части рамки — используется как метка в таблице и при сборке elem_labels
_FRAME_PART_PAD = 'Подферменник'
_FRAME_PART_BEARING = 'Опорная часть'
_FRAME_PART_VERT = 'Вертикаль'
_FRAME_PART_HORIZ = 'Горизонталь'


def _build_frame(
        model: PierModel,
        pier: PierGeometry,
        frame: FrameParameters,
        z_hinge: float,
        z_cg: float,
        z_road: float,
        include_temp: bool,
        bearing_rows: list[BearingPlaneRow],
        node_offset: int,
        elem_offset: int,
        coord_index: dict,  # общий индекс координат опоры (изменяемый)
        bearing_numbers: tuple[Optional[int], Optional[int]],  # (правый, левый) = (+Y, -Y)
) -> tuple[int, int, list[tuple[int, str]], list[BearingMeta]]:
    """
    Строит узлы и элементы одной рамки в model.

    Поддерживает несимметричное расположение подферменников:
      правый подферменник: Y = +frame.pad_y_right  (может быть задан через f1_r_pad_y)
      левый  подферменник: Y = −frame.pad_y_left   (может быть задан через f1_l_pad_y)
    При симметричном расположении pad_y_right == pad_y_left == pad_y_half_width.

    bearing_numbers = (right_bn, left_bn) соответствует (+Y, -Y).

    Вертикальные элементы z_cg → z_road и горизонталь на z_road строятся ВСЕГДА
    (не только при include_temp). include_temp влияет только на подключение
    временных масс (логика за пределами этой функции).

    Возвращает:
        new_nodes_count  — кол-во новых узлов
        new_elems_count  — кол-во новых элементов
        elem_labels      — [(elem_id, sublabel), ...] для таблицы
        bearing_metas    — метаданные ОЧ для сводки (тип BearingMeta)
    """
    x = frame.x_coordinate

    # ── Y-координаты подферменников (симметричные или нет) ───────────────────
    # Берутся из pad_y_right / pad_y_left, которые module_1 заполняет из
    # колонок f{n}_r_pad_y / f{n}_l_pad_y листа «Опоры».
    # При симметричном расположении оба равны pad_y_half_width.
    py_right: float = frame.pad_y_right
    py_left: float = frame.pad_y_left

    # Список (y_coord, bearing_number, метка_стороны)
    y_values: list[tuple[float, Optional[int], str]] = [
        (py_right, bearing_numbers[0], 'правая (+Y)'),
        (-py_left, bearing_numbers[1], 'левая  (−Y)'),
    ]

    new_nodes_count = 0
    new_elems_count = 0
    elem_labels: list[tuple[int, str]] = []
    bearing_metas: list[BearingMeta] = []

    node_local = [0]
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

    def _add_elem(ni: int, nj: int, sec: int, mat: int, label: str) -> int:
        nonlocal new_elems_count
        eid = elem_offset + elem_local[0]
        elem_local[0] += 1
        model.elements[eid] = Element(
            elem_id=eid, node_i=ni, node_j=nj,
            section_number=sec, material_number=mat,
        )
        elem_labels.append((eid, label))
        new_elems_count += 1
        return eid

    pad_top_nodes: dict[float, int] = {}

    # ── 1. Подферменники ─────────────────────────────────────────────────────
    for y, _bn, side in y_values:
        n_bot = _get_or_create(x, y, frame.pad_z_bottom)
        n_top = _get_or_create(x, y, frame.pad_z_top)
        _add_elem(n_bot, n_top, frame.pad_section, frame.pad_material,
                  f'{_FRAME_PART_PAD} ({side})')
        pad_top_nodes[y] = n_top

    # ── 2. Опорные части ─────────────────────────────────────────────────────
    hinge_nodes: dict[float, int] = {}

    for y, bn, side in y_values:
        n_bot = pad_top_nodes[y]
        n_top = _get_or_create(x, y, z_hinge)
        eid = _add_elem(n_bot, n_top, frame.bearing_section, frame.bearing_material,
                        f'{_FRAME_PART_BEARING} ({side})')
        hinge_nodes[y] = n_top

        b_type_x, b_type_y = _get_bearing_type(pier.pier_name, bn, bearing_rows)
        movable_x = (b_type_x == 'movable')
        movable_y = (b_type_y == 'movable')

        model.frame_rls[eid] = FrameRLS(
            elem_id=eid,
            release_i=(False, False, False, False, False, False),
            release_j=_make_rls(movable_x, movable_y),
        )

        h_bear = z_hinge - frame.pad_z_top
        bearing_metas.append(BearingMeta(
            side=side,
            bn=bn,
            x=x,
            y=y,
            z_bot=frame.pad_z_top,
            z_top=z_hinge,
            height=h_bear,
            type_x=b_type_x,
            type_y=b_type_y,
        ))

    # ── 3. Вертикали z_hinge → z_cg ─────────────────────────────────────────
    cg_nodes: dict[float, int] = {}

    for y, _bn, side in y_values:
        n_bot = hinge_nodes[y]
        n_top = _get_or_create(x, y, z_cg)
        _add_elem(n_bot, n_top, frame.frame_section, frame.frame_material,
                  f'{_FRAME_PART_VERT} z_hinge→z_cg ({side})')
        cg_nodes[y] = n_top

    # ── 4. Вертикали z_cg → z_road (всегда) ─────────────────────────────────
    # Строятся всегда — нужны и для постоянной схемы (no_temp), т.к. узлы
    # на z_road используются как точки приложения масс z_road.
    road_nodes: dict[float, int] = {}

    for y, _bn, side in y_values:
        n_bot = cg_nodes[y]
        n_top = _get_or_create(x, y, z_road)
        _add_elem(n_bot, n_top, frame.frame_section, frame.frame_material,
                  f'{_FRAME_PART_VERT} z_cg→z_road ({side})')
        road_nodes[y] = n_top

    # ── 5. Горизонталь 1 на z_cg ─────────────────────────────────────────────
    y_left_val = -py_left
    y_right_val = py_right
    n_left = cg_nodes[y_left_val]
    n_right = cg_nodes[y_right_val]
    n_axis = _get_or_create(x, 0.0, z_cg)

    _add_elem(n_left, n_axis, frame.frame_section, frame.frame_material,
              f'{_FRAME_PART_HORIZ} z_cg (−Y→ось)')
    _add_elem(n_axis, n_right, frame.frame_section, frame.frame_material,
              f'{_FRAME_PART_HORIZ} z_cg (ось→+Y)')

    # ── 6. Горизонталь 2 на z_road (всегда) ──────────────────────────────────
    n_left_r = road_nodes[y_left_val]
    n_right_r = road_nodes[y_right_val]
    n_axis_r = _get_or_create(x, 0.0, z_road)

    _add_elem(n_left_r, n_axis_r, frame.frame_section, frame.frame_material,
              f'{_FRAME_PART_HORIZ} z_road (−Y→ось)')
    _add_elem(n_axis_r, n_right_r, frame.frame_section, frame.frame_material,
              f'{_FRAME_PART_HORIZ} z_road (ось→+Y)')

    return new_nodes_count, new_elems_count, elem_labels, bearing_metas


def _find_bearing_numbers_for_frame(
        pier: PierGeometry,
        frame: FrameParameters,
        bearing_rows: list[BearingPlaneRow],
) -> tuple[Optional[int], Optional[int]]:
    """
    Определяет (right_bearing_number, left_bearing_number) для заданной рамки.

    Соответствие: рамка N ↔ N-е вхождение опоры в bearing_rows (по порядку).
      - Рамка 1 → первая строка опоры в «Плеть»
      - Рамка 2 → вторая строка опоры в «Плеть» (граничная опора двух плетей)

    Если индекс выходит за пределы — значит данные рассогласованы;
    validate_input_data должен был поймать это раньше, но защищаемся явно.
    """
    rows = [r for r in bearing_rows if r.pier_name == pier.pier_name]
    if not rows:
        return None, None
    idx = frame.frame_number - 1
    if idx >= len(rows):
        raise ValueError(
            f'[{pier.pier_name}] рамка {frame.frame_number} запрошена, '
            f'но в листе "Плеть" только {len(rows)} вхождений для этой опоры. '
            f'Проверьте согласованность листов "Плеть", "Массы" и "Опоры".')
    row = rows[idx]
    return row.right_bearing_number, row.left_bearing_number


def generate_frames(
        model: PierModel,
        pier: PierGeometry,
        bearing_rows: list[BearingPlaneRow],
        include_temp: bool,
        coord_index: dict,
) -> list[FrameResult]:
    """
    Часть 2 модуля 2 — строит рамки опоры.

    Добавляет узлы и элементы рамок в model, заполняет model.frame_rls.
    coord_index — общий индекс координат, созданный в generate_shaft().
    Не печатает ничего — вывод делает main через print_frames_report().

    Возвращает list[FrameResult] — данные для вывода в main.
    """
    frames_to_build: list[tuple[FrameParameters, int, int]] = []
    if pier.frame1 is not None:
        frames_to_build.append(
            (pier.frame1, pier.node_offset_frame1, pier.elem_offset_frame1))
    if pier.frame2 is not None:
        frames_to_build.append(
            (pier.frame2, pier.node_offset_frame2, pier.elem_offset_frame2))

    if not frames_to_build:
        return []

    frame_results: list[FrameResult] = []

    for frame, node_off, elem_off in frames_to_build:
        z_hinge, z_cg, z_road = _resolve_bearing_elevations(
            pier.pier_name, frame.frame_number, bearing_rows)

        bn_right, bn_left = _find_bearing_numbers_for_frame(
            pier, frame, bearing_rows)

        n_new, e_new, elem_labels, bearing_metas = _build_frame(
            model=model,
            pier=pier,
            frame=frame,
            z_hinge=z_hinge,
            z_cg=z_cg,
            z_road=z_road,
            include_temp=include_temp,
            bearing_rows=bearing_rows,
            node_offset=node_off,
            elem_offset=elem_off,
            coord_index=coord_index,
            bearing_numbers=(bn_right, bn_left),
        )

        # Y-смещения подферменников: заполнены module_1 из f{n}_r_pad_y / f{n}_l_pad_y
        py_right = frame.pad_y_right
        py_left = frame.pad_y_left

        frame_results.append(FrameResult(
            frame_number=frame.frame_number,
            x_coordinate=frame.x_coordinate,
            pad_z_bottom=frame.pad_z_bottom,
            pad_z_top=frame.pad_z_top,
            pad_y_half_width=frame.pad_y_half_width,
            pad_y_right=py_right,
            pad_y_left=py_left,
            pad_section=frame.pad_section,
            pad_material=frame.pad_material,
            bearing_section=frame.bearing_section,
            bearing_material=frame.bearing_material,
            frame_section=frame.frame_section,
            frame_material=frame.frame_material,
            z_hinge=z_hinge,
            z_cg=z_cg,
            z_road=z_road,
            include_temp=include_temp,
            n_nodes=n_new,
            n_elems=e_new,
            bearing_metas=bearing_metas,
            elem_labels=elem_labels,
        ))

    return frame_results


# ═══════════════════════════════════════════════════════════════════════════════
#  Тест Части 2
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
#  Модуль 2 — публичный API (точка входа для других модулей)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pier_geometry(
        pier: PierGeometry,
        bearing_rows: list[BearingPlaneRow] | None = None,
        include_temp: bool = False,
) -> PierGeometryResult:
    """
    Генерирует полную геометрию опоры.

    Для geom_source='parametric':
        Часть 1 (стержень): ростверк → стойка → ригель.
        Часть 2 (рамки):    подферменники → ОЧ → вертикали → горизонтали.

    Для geom_source='mct':
        Тело опоры целиком загружается из mct_file_path через load_pier_body_for_pier.
        Параметрические части (стержень, рамки) не генерируются.

    В обоих случаях, если задан pile_mct_file_path, сваи загружаются из файла.

    Не печатает ничего. Возвращает PierGeometryResult — данные для main.
    """
    # ── Вариант 1: геометрия из .mct файла ───────────────────────────────────
    if pier.geom_source == 'mct':
        model = PierModel(pier_name=pier.pier_name)
        mct_body_result: Optional[MctLoadResult] = None
        pile_result: Optional[PileLoadResult] = None

        try:
            mct_body_result = load_pier_body_for_pier(model, pier)
        except (FileNotFoundError, OSError) as exc:
            # Возвращаем результат с пустой моделью и ошибкой в mct_body_result
            err_result = MctLoadResult(
                pier_name=pier.pier_name,
                mct_path=pier.mct_file_path or '',
            )
            err_result.errors.append(str(exc))
            return PierGeometryResult(
                pier_name=pier.pier_name,
                model=None,
                mct_body_result=err_result,
            )

        # Загружаем сваи, если задан путь
        if pier.pile_mct_file_path:
            try:
                pile_result = load_piles_for_pier(model, pier)
            except (FileNotFoundError, OSError) as exc:
                if mct_body_result is not None:
                    mct_body_result.errors.append(f'Сваи: {exc}')

        return PierGeometryResult(
            pier_name=pier.pier_name,
            model=model,
            mct_body_result=mct_body_result,
            pile_result=pile_result,
        )

    # ── Вариант 2: параметрическая геометрия ─────────────────────────────────
    coord_index: dict = {}
    model, shaft_parts = generate_shaft(pier)

    for node in model.nodes.values():
        coord_index[_coord_key(node.x, node.y, node.z)] = node.node_id

    # ── Часть 2 — рамки ──────────────────────────────────────────────────────
    frame_results: list[FrameResult] = []
    has_frames = pier.frame1 is not None or pier.frame2 is not None
    if has_frames and bearing_rows is not None:
        frame_results = generate_frames(model, pier, bearing_rows,
                                        include_temp, coord_index)

    # ── Часть 3 — сваи (если задан путь) ─────────────────────────────────────
    pile_result: Optional[PileLoadResult] = None
    if pier.pile_mct_file_path:
        try:
            pile_result = load_piles_for_pier(model, pier)
        except (FileNotFoundError, OSError) as exc:
            # Не прерываем генерацию — ошибка будет видна в pile_result.errors
            dummy = PileLoadResult(
                pier_name=pier.pier_name,
                mct_path=pier.pile_mct_file_path,
                node_offset=pier.node_offset_piles,
                elem_offset=pier.elem_offset_piles,
            )
            dummy.errors.append(str(exc))
            pile_result = dummy

    return PierGeometryResult(
        pier_name=pier.pier_name,
        model=model,
        shaft_parts=shaft_parts,
        frame_results=frame_results,
        pile_result=pile_result,
    )
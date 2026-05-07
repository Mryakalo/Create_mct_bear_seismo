from typing import Optional

from additional_functions import _coord_key
from data_structures import BearingPlaneRow, PierModel, PierGeometry, FrameParameters, BearingMeta, Node, Element, \
    FrameRLS, FrameResult


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


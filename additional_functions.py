import math
from typing import Optional

from data_structures import PierModel, Node, TsGroup, BearingPlaneRow, FrameParameters, PierGeometry, MassesRow, \
    LoadPoint, Element, SoilInfluence


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции преобразования значений ячеек для модуля 1
# ═══════════════════════════════════════════════════════════════════════════════

def to_string(cell_value, default=None) -> Optional[str]:
    """
    Приводит значение ячейки Excel к строке.
    Возвращает default если значение пустое, nan или None.
    """
    if cell_value is None:
        return default
    stripped = str(cell_value).strip()
    return default if stripped in ('', 'nan', 'None') else stripped


def to_float(cell_value, default=None) -> Optional[float]:
    """
    Приводит значение ячейки Excel к числу с плавающей точкой.
    Возвращает default если преобразование невозможно.
    """
    string_value = to_string(cell_value)
    if string_value is None:
        return default
    try:
        return float(string_value)
    except ValueError:
        return default


def to_int(cell_value, default=None) -> Optional[int]:
    """
    Приводит значение ячейки Excel к целому числу.
    Возвращает default если преобразование невозможно.
    """
    string_value = to_string(cell_value)
    if string_value is None:
        return default
    try:
        return int(float(string_value))
    except ValueError:
        return default


def to_bool(cell_value) -> bool:
    """
    Приводит значение ячейки Excel к булевому.
    'да', 'yes', '1', 'true' → True, всё остальное → False.
    """
    return str(cell_value).strip().lower() in ('да', 'yes', '1', 'true')


def is_data_row(excel_row: dict, pier_name_column: str = 'pier_name') -> bool:
    """
    Проверяет, является ли строка Excel строкой с данными.
    Возвращает False для:
      - пустых строк
      - строк-разделителей плетей («Плеть 1», «Плеть 2», ...),
        включая строки с пробелами перед словом «Плеть»
      - строк-примечаний (начинаются с * после пробелов)
    """
    pier_name = to_string(excel_row.get(pier_name_column))
    if pier_name is None:
        return False
    stripped = pier_name.lstrip()
    if stripped.startswith('Плеть'):
        return False
    if stripped.startswith('*'):
        return False
    return True

# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции преобразования значений ячеек для модуля 2
# ═══════════════════════════════════════════════════════════════════════════════

_COORD_TOL = 1e-6  # допуск совпадения координат, м


def _coord_key(x: float, y: float, z: float) -> tuple[int, int, int]:
    """Дискретизированный ключ координат для быстрого поиска по словарю."""
    scale = round(1.0 / _COORD_TOL)
    return (round(x * scale), round(y * scale), round(z * scale))


def get_or_create_node(
    model: PierModel,
    x: float,
    y: float,
    z: float,
    node_offset: int,
    _coord_index: dict,         # изменяемый кэш {coord_key → node_id}, передаётся снаружи
) -> int:
    """
    Возвращает id узла с координатами (x, y, z).
    Если такого узла ещё нет — создаёт его с номером (node_offset + local_counter),
    где local_counter вычисляется из текущего размера словаря модели.

    _coord_index — общий для всей опоры индекс координат, чтобы узлы
    на границах частей (например, z = footing_z_top) не дублировались.
    """
    key = _coord_key(x, y, z)
    if key in _coord_index:
        return _coord_index[key]

    # Новый id = offset + порядковый номер в рамках этой части
    # Но так как get_or_create_node вызывается с нужным offset для каждой части,
    # используем глобальный счётчик модели, разбитый по офсетам.
    node_id = node_offset + len(
        [n for n in model.nodes.values()
         if node_offset <= n.node_id < node_offset + 1000]
    )
    node = Node(node_id=node_id, x=x, y=y, z=z)
    model.nodes[node_id] = node
    _coord_index[key] = node_id
    return node_id


_MIN_TAIL = 0.1  # м — минимальная допустимая длина последнего элемента


def _z_coordinates_for_zone(z_bottom: float, z_top: float, mesh_step: float) -> list[float]:
    """
    Возвращает список Z-координат узлов зоны [z_bottom .. z_top].

    Алгоритм:
      - Все элементы, кроме последнего, имеют длину ровно mesh_step.
      - Последний элемент получает остаток: remainder = length - n_full * mesh_step.
      - Если remainder < _MIN_TAIL (0.1 м), он присоединяется к предпоследнему
        элементу — последний узел просто не создаётся, а z_top ставится в конец
        предыдущего шага. Итого элементов = n_full - 1 + 1 (удлинённый).
      - Минимум 1 элемент (вся зона — один элемент, если length <= mesh_step).
    """
    length = z_top - z_bottom
    if length <= 0:
        raise ValueError(
            f'Некорректная зона: z_bottom={z_bottom:.4f} >= z_top={z_top:.4f}')

    n_full = int(length / mesh_step)   # количество полных шагов
    remainder = length - n_full * mesh_step

    if n_full == 0:
        # Вся зона короче mesh_step — один элемент
        return [z_bottom, z_top]

    if remainder < _MIN_TAIL - 1e-9:
        # Остаток меньше порога: поглощается последним полным элементом.
        # Элементов = n_full, узлов = n_full + 1.
        # coords[0..n_full-1] — полные шаги; coords[n_full] = z_top (удлинённый хвост).
        n_elems = n_full
    else:
        # Остаток достаточен — выделяем отдельным элементом.
        # Элементов = n_full + 1, узлов = n_full + 2.
        n_elems = n_full + 1

    # Генерируем n_elems + 1 точек: n_full полных шагов + финальная точка = z_top
    coords = [z_bottom + i * mesh_step for i in range(n_full + 1)]
    if n_elems > n_full:
        coords.append(z_top)   # остаток — отдельный элемент
    else:
        coords[-1] = z_top     # остаток поглощён: сдвигаем последнюю точку в z_top
    return coords


def _add_ts_group_element(model: PierModel, group_number: int, elem_id: int) -> None:
    """Добавляет элемент в TsGroup, создавая её при необходимости."""
    if group_number not in model.ts_groups:
        model.ts_groups[group_number] = TsGroup(group_number=group_number)
    model.ts_groups[group_number].elem_ids.append(elem_id)

# ═══════════════════════════════════════════════════════════════════════════════
#  Внутренние вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════

def _plety_rows_for_pier(bearing_plane_rows: list[BearingPlaneRow],
                         pier_name: str) -> list[BearingPlaneRow]:
    """
    Возвращает все строки листа «Плеть» для указанной опоры.

    Граничная опора двух плетей встречается дважды с разными bearing_number,
    поэтому bearing_number уникально идентифицирует нужную строку внутри
    отфильтрованного по pier_name подмножества.
    """
    return [row for row in bearing_plane_rows if row.pier_name == pier_name]


def _find_plety_row(candidate_rows: list[BearingPlaneRow],
                    bearing_number: Optional[int],
                    side: str) -> Optional[BearingPlaneRow]:
    """
    Находит строку BearingPlaneRow внутри диапазона, где номер ОЧ
    совпадает с bearing_number.

    side='right' → ищем по r_bearing_no
    side='left'  → ищем по l_bearing_no
    """
    for row in candidate_rows:
        ref = row.right_bearing_number if side == 'right' else row.left_bearing_number
        if ref == bearing_number:
            return row
    return None


def _frame_x_global(frame: FrameParameters, pier: PierGeometry) -> float:
    """X-координата рамки в локальной системе опоры (без аффинного преобразования)."""
    return frame.x_coordinate


def _pad_y_global(frame: FrameParameters, side: str, pier: PierGeometry) -> float:
    """
    Y-координата подферменника в локальной системе опоры (без аффинного преобразования).

    side='right' → +pad_y_right  (+Y сторона)
    side='left'  → −pad_y_left   (pad_y_left > 0, направление −Y)
    """
    return frame.pad_y_right if side == 'right' else -abs(frame.pad_y_left)


def _lookup_node_id(
    coord_index: dict,
    x: float,
    y: float,
    z: Optional[float],
    label: str,
    pier_name: str,
) -> Optional[int]:
    """
    Ищет узел по координатам (x, y, z) в coord_index.

    coord_index — словарь {_coord_key(x, y, z): node_id}, построенный
    в generate_pier_geometry после generate_shaft.

    Алгоритм поиска:
      1. Точное совпадение по дискретизированному ключу (x, y, z).
      2. Если точного совпадения нет — ищем ближайший узел среди всех,
         у кого (x, y) совпадают с допуском _COORD_TOL, и выбираем тот,
         у кого |z_узла - z| минимально. Это необходимо, т.к. нагрузки
         прикладываются на уровнях z_hinge/z_cg/z_road, которые не всегда
         совпадают с z-отметками узлов модели с точностью до 1e-6 м.

    Возвращает node_id или None.
    Если z is None или узел не найден — печатает предупреждение в консоль.
    """
    if z is None:
        print(
            f'  ⚠  [{pier_name}] {label}: z-отметка не определена, '
            f'узел не может быть найден (x={x:.3f}, y={y:+.3f})'
        )
        return None

    # ── Шаг 1: точное совпадение ─────────────────────────────────────────────
    key = _coord_key(x, y, z)
    node_id = coord_index.get(key)
    if node_id is not None:
        return node_id

    # ── Шаг 2: ближайший узел с совпадающими (x, y) ─────────────────────────
    # Дискретизированные (x, y) целевой точки — для фильтрации по плоскости.
    scale = round(1.0 / _COORD_TOL)
    ix_target = round(x * scale)
    iy_target = round(y * scale)

    best_node_id: Optional[int] = None
    best_dz = float('inf')

    for (ix, iy, iz), nid in coord_index.items():
        if ix != ix_target or iy != iy_target:
            continue
        dz = abs(iz - round(z * scale))
        if dz < best_dz:
            best_dz = dz
            best_node_id = nid

    if best_node_id is not None:
        # Вычисляем реальное расстояние по Z для сообщения
        best_dz_m = best_dz * _COORD_TOL
        print(
            f'  ℹ  [{pier_name}] {label}: точный узел не найден, '
            f'использован ближайший по Z (x={x:.3f}, y={y:+.3f}, '
            f'z_запрос={z:.3f}, Δz={best_dz_m:.4f} м) → node {best_node_id}'
        )
        return best_node_id

    print(
        f'  ⚠  [{pier_name}] {label}: узел не найден в модели '
        f'(x={x:.3f}, y={y:+.3f}, z={z:.3f})'
    )
    return None


def _build_load_point(pier: PierGeometry,
                      frame: FrameParameters,
                      masses_row: MassesRow,
                      plety_row: BearingPlaneRow,
                      side: str,
                      frame_number: int) -> LoadPoint:
    """
    Собирает один LoadPoint из всех источников данных.

    Параметры:
      pier         — геометрия опоры (frame1/2); аффинное преобразование не применяется
      frame        — параметры рамки (x_coordinate, pad_y_*)
      masses_row   — строка листа «Массы» (массы и z-отметки)
      plety_row    — строка листа «Плеть» (нагрузки R, тип ОЧ)
      side         — 'right' (+Y) | 'left' (−Y)
      frame_number — 1 или 2

    Разрешение z-отметок:
      z_load_permanent ← my_z   (z_cg)  — уровень ЦТ пролётного строения
      z_load_temporary ← my_t_z (z_road) — уровень проезжей части
      z_mass_X_perm    ← mx_z   (z_hinge)
      z_mass_Y_perm    ← my_z   (z_cg)
      z_mass_Z_perm    ← mz_z   (z_cg),   если нет — my_z
      z_mass_X_temp    ← mx_t_z (z_hinge), если нет — mx_z
      z_mass_Y_temp    ← my_t_z (z_road),  если нет — z_road «Плети»
      z_mass_Z_temp    ← mz_t_z (z_road),  если нет — z_road «Плети»
    """
    if side == 'right':
        bearing_number = masses_row.right_bearing_number
        mass_X_perm    = masses_row.right_mass_X_permanent
        mass_Y_perm    = masses_row.right_mass_Y_permanent
        mass_Z_perm    = masses_row.right_mass_Z_permanent
        mass_X_temp    = masses_row.right_mass_X_temporary
        mass_Y_temp    = masses_row.right_mass_Y_temporary
        mass_Z_temp    = masses_row.right_mass_Z_temporary
        # z-отметки из «Масс» (постоянные)
        mx_z   = masses_row.right_mass_X_z           # z_hinge
        my_z   = masses_row.right_mass_Y_z           # z_cg
        mz_z   = getattr(masses_row, 'right_mass_Z_z',      None)  # z_cg
        # z-отметки из «Масс» (временные)
        mx_t_z = getattr(masses_row, 'right_mass_X_temp_z', None)  # z_hinge
        my_t_z = getattr(masses_row, 'right_mass_Y_temp_z', None)  # z_road
        mz_t_z = getattr(masses_row, 'right_mass_Z_temp_z', None)  # z_road
        # нагрузки и тип ОЧ
        load_perm      = plety_row.right_load_permanent
        load_temp      = plety_row.right_load_temporary
        bearing_type_X = plety_row.right_bearing_type_X
        bearing_type_Y = plety_row.right_bearing_type_Y
    else:
        bearing_number = masses_row.left_bearing_number
        mass_X_perm    = masses_row.left_mass_X_permanent
        mass_Y_perm    = masses_row.left_mass_Y_permanent
        mass_Z_perm    = masses_row.left_mass_Z_permanent
        mass_X_temp    = masses_row.left_mass_X_temporary
        mass_Y_temp    = masses_row.left_mass_Y_temporary
        mass_Z_temp    = masses_row.left_mass_Z_temporary
        # z-отметки из «Масс» (постоянные)
        mx_z   = masses_row.left_mass_X_z            # z_hinge
        my_z   = masses_row.left_mass_Y_z            # z_cg
        mz_z   = getattr(masses_row, 'left_mass_Z_z',      None)   # z_cg
        # z-отметки из «Масс» (временные)
        mx_t_z = getattr(masses_row, 'left_mass_X_temp_z', None)   # z_hinge
        my_t_z = getattr(masses_row, 'left_mass_Y_temp_z', None)   # z_road
        mz_t_z = getattr(masses_row, 'left_mass_Z_temp_z', None)   # z_road
        # нагрузки и тип ОЧ
        load_perm      = plety_row.left_load_permanent
        load_temp      = plety_row.left_load_temporary
        bearing_type_X = plety_row.left_bearing_type_X
        bearing_type_Y = plety_row.left_bearing_type_Y

    # ── Разрешение z-отметок ─────────────────────────────────────────────────
    #
    # Вертикальные нагрузки:
    #   R_пост → z_cg   (уровень ЦТ пролётного строения)
    #   R_врем → z_road (уровень проезжей части)
    z_load_permanent = my_z   if my_z   is not None else plety_row.z_cg_elevation
    z_load_temporary = my_t_z if my_t_z is not None else plety_row.z_road_elevation

    # Постоянные массы
    z_mass_X_perm = mx_z  if mx_z  is not None else plety_row.z_hinge_elevation
    z_mass_Y_perm = my_z  if my_z  is not None else plety_row.z_cg_elevation
    z_mass_Z_perm = (mz_z if mz_z  is not None else
                     my_z if my_z  is not None else plety_row.z_cg_elevation)

    # Временные массы
    z_mass_X_temp = (mx_t_z if mx_t_z is not None else
                     mx_z   if mx_z   is not None else plety_row.z_hinge_elevation)
    z_mass_Y_temp = my_t_z if my_t_z is not None else plety_row.z_road_elevation
    z_mass_Z_temp = mz_t_z if mz_t_z is not None else plety_row.z_road_elevation

    return LoadPoint(
        pier_name      = pier.pier_name,
        bearing_number = bearing_number,
        side           = side,
        frame_number   = frame_number,

        x = _frame_x_global(frame, pier),
        y = _pad_y_global(frame, side, pier),

        z_load_permanent = z_load_permanent,
        z_load_temporary = z_load_temporary,
        z_mass_X_perm    = z_mass_X_perm,
        z_mass_Y_perm    = z_mass_Y_perm,
        z_mass_Z_perm    = z_mass_Z_perm,
        z_mass_X_temp    = z_mass_X_temp,
        z_mass_Y_temp    = z_mass_Y_temp,
        z_mass_Z_temp    = z_mass_Z_temp,

        load_permanent = load_perm,
        load_temporary = load_temp,

        mass_X_permanent = mass_X_perm,
        mass_Y_permanent = mass_Y_perm,
        mass_Z_permanent = mass_Z_perm,

        mass_X_temporary = mass_X_temp,
        mass_Y_temporary = mass_Y_temp,
        mass_Z_temporary = mass_Z_temp,

        bearing_type_X = bearing_type_X,
        bearing_type_Y = bearing_type_Y,
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции модуль 3 часть 2
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  Типы элементов опоры
# ═══════════════════════════════════════════════════════════════════════════════

_ELEM_TYPE_PILE     = 'сваи'
_ELEM_TYPE_FOOTING  = 'ростверк'
_ELEM_TYPE_BODY     = 'тело опоры'   # стойка + ригель

def _elem_z_range(model: PierModel, elem: Element) -> tuple[float, float]:
    """Возвращает (z_min, z_max) узлов элемента."""
    node_i = model.nodes[elem.node_i]
    node_j = model.nodes[elem.node_j]
    return min(node_i.z, node_j.z), max(node_i.z, node_j.z)


def _overlap_length(z_i: float, z_j: float,
                    z_bot: float, z_top: float) -> float:
    """
    Длина пересечения отрезка [z_i, z_j] с зоной [z_bot, z_top].
    Возвращает 0.0, если пересечения нет.
    """
    lo = max(min(z_i, z_j), z_bot)
    hi = min(max(z_i, z_j), z_top)
    return max(0.0, hi - lo)


def _classify_element(elem: Element, pier: PierGeometry) -> str:
    """
    Определяет тип элемента по его id относительно офсетов PierGeometry.

    Сваи:     [node_offset_piles .. +∞)     — наибольший офсет
    Ростверк: [elem_offset_footing .. elem_offset_column)
    Тело:     [elem_offset_column  .. elem_offset_piles)  (стойка + ригель)
    """
    eid = elem.elem_id
    if eid >= pier.elem_offset_piles:
        return _ELEM_TYPE_PILE
    if eid >= pier.elem_offset_footing and eid < pier.elem_offset_column:
        return _ELEM_TYPE_FOOTING
    return _ELEM_TYPE_BODY


def _mean_area_for_element(
    elem: Element,
    elem_type: str,
    soil: SoilInfluence,
    z_mid: float,
    pier: PierGeometry,
    warnings: list[str],
) -> Optional[float]:
    """
    Вычисляет среднюю площадь поперечного сечения элемента.

    Площади в SoilInfluence задаются попарно (top/bottom) для каждой зоны.
    Зона определяется по section_number элемента, сопоставленному с зонами
    PierGeometry (footing_zones / column_zones).

    Для сваи всегда берётся единственная пара pile_area_{top,bottom},
    а линейная интерполяция выполняется между низом и верхом зоны.

    Параметр z_mid — средняя Z-отметка участка элемента в зоне воздействия
    (используется для интерполяции).
    """
    sec = elem.section_number

    # ── Сваи ─────────────────────────────────────────────────────────────────
    if elem_type == _ELEM_TYPE_PILE:
        a_top = soil.pile_area_top
        a_bot = soil.pile_area_bottom
        if a_top is None or a_bot is None:
            warnings.append(
                f'  ⚠  [{soil.pier_name}] элемент {elem.elem_id} (свая, sec={sec}): '
                f'pile_area_top/bottom не заданы — элемент пропущен'
            )
            return None
        # Интерполяция между верхом и низом зоны воздействия выполняется
        # в вызывающей функции; здесь возвращаем среднее top/bottom.
        return (a_top + a_bot) / 2.0

    # ── Ростверк ─────────────────────────────────────────────────────────────
    if elem_type == _ELEM_TYPE_FOOTING:
        zones_areas = [
            (soil.footing_area_sec1_top, soil.footing_area_sec1_bottom),
            (soil.footing_area_sec2_top, soil.footing_area_sec2_bottom),
        ]
        pier_zones = pier.footing_zones

    # ── Тело опоры (стойка + ригель) ─────────────────────────────────────────
    else:
        zones_areas = [
            (soil.column_area_sec1_top, soil.column_area_sec1_bottom),
            (soil.column_area_sec2_top, soil.column_area_sec2_bottom),
            (soil.column_area_sec3_top, soil.column_area_sec3_bottom),
        ]
        pier_zones = pier.column_zones

    # Ищем зону, section_number которой совпадает с номером сечения элемента
    matching_zone_idx: Optional[int] = None
    for idx, pz in enumerate(pier_zones):
        if pz.section_number == sec and idx < len(zones_areas):
            matching_zone_idx = idx
            break

    if matching_zone_idx is None:
        # Сечение не найдено в зонах — берём первую доступную пару как fallback
        matching_zone_idx = 0
        warnings.append(
            f'  ℹ  [{soil.pier_name}] элемент {elem.elem_id} '
            f'(тип={elem_type}, sec={sec}): '
            f'сечение не найдено в зонах, используется зона 1'
        )

    a_top, a_bot = zones_areas[matching_zone_idx]

    if a_top is None or a_bot is None:
        warnings.append(
            f'  ⚠  [{soil.pier_name}] элемент {elem.elem_id} '
            f'(тип={elem_type}, sec={sec}, зона {matching_zone_idx + 1}): '
            f'площадь сечения не задана — элемент пропущен'
        )
        return None

    # Линейная интерполяция: знаем A в верху и низу зоны PierGeometry
    # Для получения A в произвольной точке z используем z_mid элемента
    # относительно диапазона соответствующей зоны.
    if pier_zones:
        pz = pier_zones[matching_zone_idx]
        # Нижняя граница зоны: предыдущая zone_z_top или 0 (для ростверка)
        if matching_zone_idx == 0:
            z_zone_bot = 0.0  # низ первой зоны = низ ростверка
        else:
            z_zone_bot = pier_zones[matching_zone_idx - 1].zone_z_top
        z_zone_top = pz.zone_z_top
        zone_height = z_zone_top - z_zone_bot
        if zone_height > 1e-9:
            t = max(0.0, min(1.0, (z_mid - z_zone_bot) / zone_height))
            # t=0 → низ зоны (a_bot), t=1 → верх зоны (a_top)
            return a_bot + t * (a_top - a_bot)

    return (a_top + a_bot) / 2.0

# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════

def _active_pressure_coeff(friction_angle_deg: float) -> float:
    """
    Коэффициент активного давления Ренкина:
        Ka = tan²(45° − φ/2)
    """
    phi_rad = math.radians(friction_angle_deg / 2.0)
    return math.tan(math.radians(45.0) - phi_rad) ** 2


def _active_pressure_at_z(
    z_node: float,
    z_surface: float,
    z_bottom: float,
    gamma: float,
    ka: float,
) -> float:
    """
    Активное давление грунта в точке z_node [тс/м²]:
        p = γ · Ka · h,  h = z_surface − z_node
    Возвращает 0, если узел выше поверхности или ниже низа зоны.
    """
    if z_node > z_surface or z_node < z_bottom:
        return 0.0
    h = z_surface - z_node
    return gamma * ka * h


def _interpolate_width(
    z: float,
    z_top_zone: float,
    z_bot_zone: float,
    width_top: float,
    width_bot: float,
) -> float:
    """
    Линейная интерполяция ширины внутри зоны по Z.

    t = 0 → низ зоны (width_bot); t = 1 → верх зоны (width_top).
    Если зона вырождена — возвращает среднее.
    """
    span = z_top_zone - z_bot_zone
    if span < 1e-9:
        return (width_top + width_bot) / 2.0
    t = max(0.0, min(1.0, (z - z_bot_zone) / span))
    return width_bot + t * (width_top - width_bot)


def _get_width_at_z(
    z: float,
    elem: Element,
    elem_type: str,
    pier: PierGeometry,
    soil: SoilInfluence,
    warnings: list[str],
) -> Optional[float]:
    """
    Возвращает ширину сечения элемента на отметке z методом линейной
    интерполяции внутри зоны, к которой принадлежит элемент.

    Ширины задаются в SoilInfluence по секциям и типу элемента.
    section_number элемента сопоставляется с зонами PierGeometry, как в
    _mean_area_for_element (additional_functions.py).
    """
    sec = elem.section_number

    # ── Сваи ────────────────────────────────────────────────────────────────
    if elem_type == _ELEM_TYPE_PILE:
        w = soil.pile_width
        if w is None:
            warnings.append(
                f'  ⚠  [{soil.pier_name}] элемент {elem.elem_id} (свая): '
                f'pile_width не задан — элемент пропущен'
            )
        return w

    # ── Ростверк ─────────────────────────────────────────────────────────────
    if elem_type == _ELEM_TYPE_FOOTING:
        zones_widths = [
            soil.footing_sec1_width,
            soil.footing_sec2_width,
        ]
        pier_zones = pier.footing_zones

    # ── Тело опоры (стойка + ригель) ─────────────────────────────────────────
    else:
        zones_widths = [
            soil.column_sec1_width,
            soil.column_sec2_width,
            soil.column_sec3_width,
        ]
        pier_zones = pier.column_zones

    # Ищем зону по section_number элемента
    matching_idx: Optional[int] = None
    for idx, pz in enumerate(pier_zones):
        if pz.section_number == sec and idx < len(zones_widths):
            matching_idx = idx
            break

    if matching_idx is None:
        matching_idx = 0
        warnings.append(
            f'  ℹ  [{soil.pier_name}] элемент {elem.elem_id} '
            f'(тип={elem_type}, sec={sec}): '
            f'сечение не найдено в зонах — используется зона 1 для ширины'
        )

    w = zones_widths[matching_idx]
    if w is None:
        warnings.append(
            f'  ⚠  [{soil.pier_name}] элемент {elem.elem_id} '
            f'(тип={elem_type}, sec={sec}, зона {matching_idx + 1}): '
            f'ширина сечения не задана — элемент пропущен'
        )
        return None

    # Для сваи и простых (не переменных) сечений ширина константа — возвращаем сразу.
    # Для ростверка и стойки ширина может линейно изменяться между верхом и низом зоны,
    # если бы были заданы раздельные значения. В текущей структуре SoilInfluence
    # ширина задана единым значением на зону — возвращаем его.
    return w


def _width_at_z_for_node(
    z: float,
    elem: Element,
    elem_type: str,
    pier: PierGeometry,
    soil: SoilInfluence,
    warnings: list[str],
) -> Optional[float]:
    """
    Ширина сечения на отметке z с линейной интерполяцией внутри зоны PierGeometry.

    Если у элемента известна зона, для которой задана ширина и верхняя/нижняя
    границы зоны — выполняется интерполяция. Иначе — возвращается единственное
    значение ширины зоны без интерполяции.

    Для тела опоры ширина может изменяться между зонами (стойка нижняя /
    стойка верхняя). Внутри одной зоны ширина считается постоянной (одно
    значение на зону в SoilInfluence). Если потребуется переменная ширина внутри
    зоны — следует расширить SoilInfluence полями *_top / *_bottom.
    """
    sec = elem.section_number

    if elem_type == _ELEM_TYPE_PILE:
        return _get_width_at_z(z, elem, elem_type, pier, soil, warnings)

    if elem_type == _ELEM_TYPE_FOOTING:
        pier_zones = pier.footing_zones
        zones_widths = [
            soil.footing_sec1_width,
            soil.footing_sec2_width,
        ]
    else:
        pier_zones = pier.column_zones
        zones_widths = [
            soil.column_sec1_width,
            soil.column_sec2_width,
            soil.column_sec3_width,
        ]

    matching_idx: Optional[int] = None
    for idx, pz in enumerate(pier_zones):
        if pz.section_number == sec and idx < len(zones_widths):
            matching_idx = idx
            break

    if matching_idx is None:
        matching_idx = 0

    w = zones_widths[matching_idx]
    if w is None:
        return None

    # Границы зоны
    if matching_idx == 0:
        z_zone_bot = 0.0
    else:
        z_zone_bot = pier_zones[matching_idx - 1].zone_z_top
    z_zone_top = pier_zones[matching_idx].zone_z_top

    # Ширина внутри зоны постоянна (одно значение на зону):
    # интерполируем как константу, но сохраняем структуру для будущего расширения.
    return _interpolate_width(z, z_zone_top, z_zone_bot, w, w)

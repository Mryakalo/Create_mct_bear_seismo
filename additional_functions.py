import math
from typing import Optional

from data_structures import PierModel, Node, TsGroup, BearingPlaneRow, FrameParameters, PierGeometry, MassesRow, \
    LoadPoint


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

    Возвращает node_id или None.
    Если z is None или узел не найден — печатает предупреждение в консоль.
    """
    if z is None:
        print(
            f'  ⚠  [{pier_name}] {label}: z-отметка не определена, '
            f'узел не может быть найден (x={x:.3f}, y={y:+.3f})'
        )
        return None

    key = _coord_key(x, y, z)
    node_id = coord_index.get(key)

    if node_id is None:
        print(
            f'  ⚠  [{pier_name}] {label}: узел не найден в модели '
            f'(x={x:.3f}, y={y:+.3f}, z={z:.3f})'
        )

    return node_id


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
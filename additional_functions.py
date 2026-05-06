import math
from typing import Optional

from data_structures import PierModel, Node, TsGroup


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


def _z_coordinates_for_zone(z_bottom: float, z_top: float, mesh_step: float) -> list[float]:
    """
    Возвращает список Z-координат узлов зоны [z_bottom .. z_top]
    с шагом не более mesh_step (равномерное разбиение).
    Всегда включает оба конца. Минимум 2 точки → 1 элемент.
    """
    length = z_top - z_bottom
    if length <= 0:
        raise ValueError(
            f'Некорректная зона: z_bottom={z_bottom:.4f} >= z_top={z_top:.4f}')
    n_elements = max(1, math.ceil(length / mesh_step))
    step = length / n_elements
    coords = [z_bottom + i * step for i in range(n_elements + 1)]
    # Корректируем последнюю точку на случай накопленной погрешности
    coords[-1] = z_top
    return coords


def _add_ts_group_element(model: PierModel, group_number: int, elem_id: int) -> None:
    """Добавляет элемент в TsGroup, создавая её при необходимости."""
    if group_number not in model.ts_groups:
        model.ts_groups[group_number] = TsGroup(group_number=group_number)
    model.ts_groups[group_number].elem_ids.append(elem_id)
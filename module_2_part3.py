"""
module_2_part3.py — Часть 3 Модуля 2: импорт геометрии из .mct файла

Два публичных API:

1. load_piles_from_mct(model, node_offset, elem_offset, mct_path) → PileLoadResult
   Читает узлы (*NODE), элементы-балки (*ELEMENT BEAM) и упругие опоры (*SPRING)
   из .mct файла свай. Перенумеровывает узлы и элементы согласно порядку:
   X убывает → Y убывает → Z убывает.
   Номера пружин (*SPRING) совпадают с номерами узлов.

2. load_pier_body_from_mct(model, node_offset, elem_offset, mct_path) → MctLoadResult
   Читает полную геометрию тела опоры из .mct файла (geom_source='mct').
   Узлы и элементы добавляются в модель «как есть» (без пересортировки),
   начиная с node_offset_footing / elem_offset_footing.
   Собирает статистику: количество узлов, элементов, пружин,
   уникальные номера материалов и сечений.

Секции *RIGIDLINK, *GROUP, *CONSTRAINT — пропускаются.

Вспомогательные обёртки для вызова из generate_pier_geometry (module_2.py):
    load_piles_for_pier(model, pier)      → Optional[PileLoadResult]
    load_pier_body_for_pier(model, pier)  → Optional[MctLoadResult]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from data_structures import (
    Element, Node, PierModel, SpringSupport,
)
from additional_functions import _coord_key


# ═══════════════════════════════════════════════════════════════════════════════
#  Внутренние структуры для хранения «сырых» данных из .mct
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class _RawNode:
    orig_id: int
    x: float
    y: float
    z: float


@dataclass
class _RawElement:
    orig_id: int
    elem_type: str   # 'BEAM', и т.д.
    section:   int
    material:  int
    node_i:    int   # оригинальный id
    node_j:    int   # оригинальный id
    beta:      int   # угол бета (последнее поле строки элемента)


@dataclass
class _RawSpring:
    orig_node_id: int
    spring_type:  str
    sdx:          float
    sdy:          float
    raw_tail:     str   # всё после sdy — дословно


# ═══════════════════════════════════════════════════════════════════════════════
#  Результирующие структуры (для вывода в main/mct_generator)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PileLoadResult:
    """Итог импорта свай из .mct файла (для вывода в main)."""
    pier_name:      str
    mct_path:       str
    n_nodes:        int = 0
    n_elements:     int = 0
    n_springs:      int = 0
    node_offset:    int = 0
    elem_offset:    int = 0
    # Диапазоны новых id после перенумерации
    node_id_min:      Optional[int] = None
    node_id_max:      Optional[int] = None
    elem_id_min:      Optional[int] = None
    elem_id_max:      Optional[int] = None
    # Уникальные номера материалов и сечений (отсортированы)
    material_numbers: list[int] = field(default_factory=list)
    section_numbers:  list[int] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)


@dataclass
class MctLoadResult:
    """
    Итог импорта тела опоры из .mct файла (geom_source='mct').

    Содержит полную статистику для вывода в main:
      - количество узлов, элементов, пружин
      - уникальные номера материалов и сечений из *ELEMENT
      - диапазоны id узлов и элементов в модели
    """
    pier_name:        str
    mct_path:         str
    n_nodes:          int       = 0
    n_elements:       int       = 0
    n_springs:        int       = 0
    node_offset:      int       = 0
    elem_offset:      int       = 0
    node_id_min:      Optional[int] = None
    node_id_max:      Optional[int] = None
    elem_id_min:      Optional[int] = None
    elem_id_max:      Optional[int] = None
    # Уникальные номера материалов и сечений (отсортированы)
    material_numbers: list[int] = field(default_factory=list)
    section_numbers:  list[int] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
#  Парсинг .mct файла
# ═══════════════════════════════════════════════════════════════════════════════

_SECTION_RE = re.compile(r'^\*([A-Z_]+)', re.IGNORECASE)

# Секции, которые нужно читать
_SECTION_NODE    = 'NODE'
_SECTION_ELEMENT = 'ELEMENT'
_SECTION_SPRING  = 'SPRING'

# Секции, которые пропускаются целиком
_SKIP_SECTIONS = {'RIGIDLINK', 'GROUP', 'CONSTRAINT'}


def _parse_mct(mct_path: str) -> tuple[
    list[_RawNode],
    list[_RawElement],
    list[_RawSpring],
    list[str],       # warnings/errors
]:
    """
    Разбирает .mct файл, возвращает сырые данные по узлам, элементам и пружинам.
    Элементы с типом, отличным от BEAM, не добавляются в список (пишется warning).
    """
    raw_nodes:    list[_RawNode]    = []
    raw_elements: list[_RawElement] = []
    raw_springs:  list[_RawSpring]  = []
    errors:       list[str]         = []

    current_section: Optional[str] = None

    with open(mct_path, encoding='utf-8', errors='replace') as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()

            # Пустые строки и комментарии
            if not line or line.startswith(';'):
                continue

            # Заголовок секции
            m = _SECTION_RE.match(line)
            if m:
                current_section = m.group(1).upper()
                continue

            # Пропускаем ненужные секции
            if current_section in _SKIP_SECTIONS or current_section is None:
                continue

            # ── *NODE ─────────────────────────────────────────────────────────
            if current_section == _SECTION_NODE:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 4:
                    errors.append(f'строка {lineno}: неверный формат NODE: {line!r}')
                    continue
                try:
                    raw_nodes.append(_RawNode(
                        orig_id=int(parts[0]),
                        x=float(parts[1]),
                        y=float(parts[2]),
                        z=float(parts[3]),
                    ))
                except ValueError as exc:
                    errors.append(f'строка {lineno}: ошибка NODE: {exc}')

            # ── *ELEMENT ──────────────────────────────────────────────────────
            elif current_section == _SECTION_ELEMENT:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 7:
                    errors.append(f'строка {lineno}: неверный формат ELEMENT: {line!r}')
                    continue
                try:
                    elem_type = parts[1].strip().upper()
                    if elem_type != 'BEAM':
                        errors.append(
                            f'строка {lineno}: пропущен элемент типа {elem_type!r} '
                            f'(ожидается BEAM)')
                        continue
                    raw_elements.append(_RawElement(
                        orig_id=int(parts[0]),
                        elem_type=elem_type,
                        section=int(parts[2]),
                        material=int(parts[3]),
                        node_i=int(parts[4]),
                        node_j=int(parts[5]),
                        beta=int(parts[6]),
                    ))
                except ValueError as exc:
                    errors.append(f'строка {lineno}: ошибка ELEMENT: {exc}')

            # ── *SPRING ───────────────────────────────────────────────────────
            elif current_section == _SECTION_SPRING:
                # Формат: node_id, TYPE, sdx, sdy, <остаток>
                parts = line.split(',', maxsplit=3)
                if len(parts) < 4:
                    errors.append(f'строка {lineno}: неверный формат SPRING: {line!r}')
                    continue
                try:
                    raw_springs.append(_RawSpring(
                        orig_node_id=int(parts[0].strip()),
                        spring_type=parts[1].strip(),
                        sdx=float(parts[2].strip()),
                        sdy=float(parts[3].strip().split(',')[0]),
                        raw_tail=_extract_tail_after_sdy(parts[3]),
                    ))
                except ValueError as exc:
                    errors.append(f'строка {lineno}: ошибка SPRING: {exc}')

    return raw_nodes, raw_elements, raw_springs, errors


def _extract_tail_after_sdy(fourth_field: str) -> str:
    """
    В строке SPRING после разбивки split(',', maxsplit=3)
    четвёртое поле содержит: '<sdy>, <остаток>'.
    Возвращаем всё начиная с первой запятой (включительно), т.е. ', <остаток>'.
    """
    comma_pos = fourth_field.find(',')
    if comma_pos == -1:
        return ''
    return fourth_field[comma_pos:]


# ═══════════════════════════════════════════════════════════════════════════════
#  Определение порядка нумерации (для свай)
# ═══════════════════════════════════════════════════════════════════════════════

def _sort_key_for_node(node: _RawNode) -> tuple[float, float, float]:
    """
    Ключ сортировки узлов: X убывает, потом Y убывает, потом Z убывает.
    (Z убывает означает: от наибольшего значения, т.е. от верха сваи к низу).
    """
    return (-node.x, -node.y, -node.z)


def _build_node_id_map(
    raw_nodes: list[_RawNode],
    node_offset: int,
) -> dict[int, int]:
    """
    Строит словарь {orig_node_id → new_node_id}.

    Порядок нумерации: X убывает → Y убывает → Z убывает.
    Первый новый id = node_offset.
    """
    sorted_nodes = sorted(raw_nodes, key=_sort_key_for_node)
    return {
        node.orig_id: node_offset + idx
        for idx, node in enumerate(sorted_nodes)
    }


def _sort_key_for_element(
    elem: _RawElement,
    node_map: dict[int, int],
    orig_nodes: dict[int, _RawNode],
) -> tuple[float, float, float]:
    """
    Ключ сортировки элементов: по координатам узла i (начало элемента).
    Тот же порядок: X убывает → Y убывает → Z убывает.
    """
    ni = orig_nodes[elem.node_i]
    return (-ni.x, -ni.y, -ni.z)


def _build_elem_id_map(
    raw_elements: list[_RawElement],
    elem_offset: int,
    orig_nodes: dict[int, _RawNode],
) -> dict[int, int]:
    """
    Строит словарь {orig_elem_id → new_elem_id}.

    Порядок нумерации: по узлу i элемента — X убывает → Y убывает → Z убывает.
    Первый новый id = elem_offset.
    """
    sorted_elems = sorted(
        raw_elements,
        key=lambda e: _sort_key_for_element(e, {}, orig_nodes),
    )
    return {
        elem.orig_id: elem_offset + idx
        for idx, elem in enumerate(sorted_elems)
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция — сваи
# ═══════════════════════════════════════════════════════════════════════════════

def load_piles_from_mct(
    model:    PierModel,
    node_offset: int,
    elem_offset: int,
    mct_path: str,
) -> PileLoadResult:
    """
    Читает геометрию свай из .mct файла, перенумеровывает узлы и элементы
    и добавляет их в существующую модель опоры.

    Параметры
    ---------
    model       : PierModel — модель, в которую добавляются данные свай.
    node_offset : int       — начальный id для перенумерации узлов свай
                              (обычно pier.node_offset_piles).
    elem_offset : int       — начальный id для перенумерации элементов свай
                              (обычно pier.elem_offset_piles).
    mct_path    : str       — путь к .mct файлу свай.

    Возвращает
    ----------
    PileLoadResult — сводка по импортированным данным.

    Побочные эффекты
    ----------------
    Заполняет model.nodes, model.elements, model.springs.
    Узлы добавляются только если coord_key ещё не занят в модели
    (защита от дублирования на стыке с ростверком).

    Секции *RIGIDLINK, *GROUP, *CONSTRAINT — пропускаются.
    Пружины (*SPRING) перенумеровываются вместе с узлами.
    """
    result = PileLoadResult(
        pier_name=model.pier_name,
        mct_path=mct_path,
        node_offset=node_offset,
        elem_offset=elem_offset,
    )

    # ── 1. Парсинг файла ──────────────────────────────────────────────────────
    raw_nodes, raw_elements, raw_springs, parse_errors = _parse_mct(mct_path)
    result.errors.extend(parse_errors)

    if not raw_nodes:
        result.errors.append(f'В файле {mct_path!r} не найдено ни одного узла')
        return result

    # Индекс orig_id → _RawNode (нужен при сортировке элементов)
    orig_nodes_idx: dict[int, _RawNode] = {n.orig_id: n for n in raw_nodes}

    # ── 2. Построение маппингов перенумерации ─────────────────────────────────
    node_id_map: dict[int, int] = _build_node_id_map(raw_nodes, node_offset)
    elem_id_map: dict[int, int] = _build_elem_id_map(
        raw_elements, elem_offset, orig_nodes_idx)

    # ── 3. Строим coord_index из уже существующих узлов модели ───────────────
    existing_coord_index: dict = {
        _coord_key(n.x, n.y, n.z): nid
        for nid, n in model.nodes.items()
    }

    # ── 4. Добавляем узлы в модель ────────────────────────────────────────────
    added_nodes = 0
    for raw_node in raw_nodes:
        new_id = node_id_map[raw_node.orig_id]
        key = _coord_key(raw_node.x, raw_node.y, raw_node.z)

        if key in existing_coord_index:
            # Узел уже есть в модели — переиспользуем и обновляем маппинг
            node_id_map[raw_node.orig_id] = existing_coord_index[key]
            continue

        node = Node(node_id=new_id, x=raw_node.x, y=raw_node.y, z=raw_node.z)
        model.nodes[new_id] = node
        existing_coord_index[key] = new_id
        added_nodes += 1

    result.n_nodes = added_nodes

    # ── 5. Добавляем элементы в модель ────────────────────────────────────────
    sorted_raw_elems = sorted(
        raw_elements,
        key=lambda e: _sort_key_for_element(e, {}, orig_nodes_idx),
    )

    added_elems = 0
    material_set: set[int] = set()
    section_set:  set[int] = set()
    for raw_elem in sorted_raw_elems:
        new_eid  = elem_id_map[raw_elem.orig_id]
        new_ni   = node_id_map[raw_elem.node_i]
        new_nj   = node_id_map[raw_elem.node_j]

        elem = Element(
            elem_id=new_eid,
            node_i=new_ni,
            node_j=new_nj,
            section_number=raw_elem.section,
            material_number=raw_elem.material,
        )
        model.elements[new_eid] = elem
        material_set.add(raw_elem.material)
        section_set.add(raw_elem.section)
        added_elems += 1

    result.n_elements        = added_elems
    result.material_numbers  = sorted(material_set)
    result.section_numbers   = sorted(section_set)

    # ── 6. Добавляем пружины в модель ─────────────────────────────────────────
    added_springs = 0
    for raw_spring in raw_springs:
        if raw_spring.orig_node_id not in node_id_map:
            result.errors.append(
                f'SPRING: узел {raw_spring.orig_node_id} не найден среди '
                f'узлов свай — пружина пропущена')
            continue

        new_node_id = node_id_map[raw_spring.orig_node_id]
        spring = SpringSupport(
            node_id=new_node_id,
            spring_type=raw_spring.spring_type,
            sdx=raw_spring.sdx,
            sdy=raw_spring.sdy,
            raw_tail=raw_spring.raw_tail,
        )
        model.springs[new_node_id] = spring
        added_springs += 1

    result.n_springs = added_springs

    # ── 7. Диапазоны id ───────────────────────────────────────────────────────
    pile_node_ids = [
        node_id_map[n.orig_id] for n in raw_nodes
        if node_id_map[n.orig_id] in model.nodes
    ]
    pile_elem_ids = list(elem_id_map.values())

    if pile_node_ids:
        result.node_id_min = min(pile_node_ids)
        result.node_id_max = max(pile_node_ids)
    if pile_elem_ids:
        result.elem_id_min = min(pile_elem_ids)
        result.elem_id_max = max(pile_elem_ids)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция — тело опоры из .mct (geom_source='mct')
# ═══════════════════════════════════════════════════════════════════════════════

def load_pier_body_from_mct(
    model:       PierModel,
    node_offset: int,
    elem_offset: int,
    mct_path:    str,
) -> MctLoadResult:
    """
    Читает полную геометрию тела опоры из .mct файла и добавляет её в модель.

    В отличие от load_piles_from_mct, узлы и элементы НЕ пересортировываются —
    нумерация сохраняется «как в файле», но сдвигается на offset:
        new_id = offset + (orig_id - min_orig_id_в_файле)
    Это гарантирует компактный диапазон без дырок, начинающийся с offset.

    Пружины (*SPRING) перенумеровываются вместе с узлами.
    Секции *RIGIDLINK, *GROUP, *CONSTRAINT — пропускаются.

    Возвращает MctLoadResult со статистикой:
        n_nodes, n_elements, n_springs,
        material_numbers, section_numbers (отсортированы),
        node_id_min, node_id_max, elem_id_min, elem_id_max.
    """
    result = MctLoadResult(
        pier_name=model.pier_name,
        mct_path=mct_path,
        node_offset=node_offset,
        elem_offset=elem_offset,
    )

    # ── 1. Парсинг файла ──────────────────────────────────────────────────────
    raw_nodes, raw_elements, raw_springs, parse_errors = _parse_mct(mct_path)
    result.errors.extend(parse_errors)

    if not raw_nodes:
        result.errors.append(f'В файле {mct_path!r} не найдено ни одного узла')
        return result

    # ── 2. Построение маппингов (orig_id → new_id) ────────────────────────────
    # Сохраняем относительный порядок из файла, сдвигая на offset.
    min_node_orig = min(n.orig_id for n in raw_nodes)
    node_id_map: dict[int, int] = {
        n.orig_id: node_offset + (n.orig_id - min_node_orig)
        for n in raw_nodes
    }

    min_elem_orig = min(e.orig_id for e in raw_elements) if raw_elements else 0
    elem_id_map: dict[int, int] = {
        e.orig_id: elem_offset + (e.orig_id - min_elem_orig)
        for e in raw_elements
    }

    # ── 3. Coord-индекс уже существующих узлов (защита от дублирования) ───────
    existing_coord_index: dict = {
        _coord_key(n.x, n.y, n.z): nid
        for nid, n in model.nodes.items()
    }

    # ── 4. Добавляем узлы в модель ────────────────────────────────────────────
    added_nodes = 0
    for raw_node in raw_nodes:
        new_id = node_id_map[raw_node.orig_id]
        key = _coord_key(raw_node.x, raw_node.y, raw_node.z)

        if key in existing_coord_index:
            # Дублирующийся по координатам узел — переиспользуем и обновляем маппинг
            node_id_map[raw_node.orig_id] = existing_coord_index[key]
            continue

        model.nodes[new_id] = Node(node_id=new_id, x=raw_node.x,
                                   y=raw_node.y, z=raw_node.z)
        existing_coord_index[key] = new_id
        added_nodes += 1

    result.n_nodes = added_nodes

    # ── 5. Добавляем элементы в модель ────────────────────────────────────────
    added_elems = 0
    material_set: set[int] = set()
    section_set:  set[int] = set()

    for raw_elem in raw_elements:
        new_eid = elem_id_map[raw_elem.orig_id]
        new_ni  = node_id_map[raw_elem.node_i]
        new_nj  = node_id_map[raw_elem.node_j]

        model.elements[new_eid] = Element(
            elem_id=new_eid,
            node_i=new_ni,
            node_j=new_nj,
            section_number=raw_elem.section,
            material_number=raw_elem.material,
        )
        material_set.add(raw_elem.material)
        section_set.add(raw_elem.section)
        added_elems += 1

    result.n_elements   = added_elems
    result.material_numbers = sorted(material_set)
    result.section_numbers  = sorted(section_set)

    # ── 6. Добавляем пружины в модель ─────────────────────────────────────────
    added_springs = 0
    for raw_spring in raw_springs:
        if raw_spring.orig_node_id not in node_id_map:
            result.errors.append(
                f'SPRING: узел {raw_spring.orig_node_id} не найден '
                f'в узлах тела опоры — пружина пропущена')
            continue

        new_node_id = node_id_map[raw_spring.orig_node_id]
        model.springs[new_node_id] = SpringSupport(
            node_id=new_node_id,
            spring_type=raw_spring.spring_type,
            sdx=raw_spring.sdx,
            sdy=raw_spring.sdy,
            raw_tail=raw_spring.raw_tail,
        )
        added_springs += 1

    result.n_springs = added_springs

    # ── 7. Диапазоны id ───────────────────────────────────────────────────────
    body_node_ids = [v for v in node_id_map.values() if v in model.nodes]
    body_elem_ids = [v for v in elem_id_map.values() if v in model.elements]

    if body_node_ids:
        result.node_id_min = min(body_node_ids)
        result.node_id_max = max(body_node_ids)
    if body_elem_ids:
        result.elem_id_min = min(body_elem_ids)
        result.elem_id_max = max(body_elem_ids)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные обёртки для интеграции в generate_pier_geometry (module_2.py)
# ═══════════════════════════════════════════════════════════════════════════════

def load_piles_for_pier(model: PierModel, pier) -> Optional[PileLoadResult]:
    """
    Обёртка для вызова из generate_pier_geometry:
    читает pile_mct_file_path из PierGeometry и загружает сваи в модель.

    Возвращает None если pile_mct_file_path не задан.
    Выбрасывает FileNotFoundError если файл не найден.
    """
    from data_structures import PierGeometry  # локальный импорт избегает цикла
    assert isinstance(pier, PierGeometry)

    if not pier.pile_mct_file_path:
        return None

    mct_path = Path(pier.pile_mct_file_path)
    if not mct_path.exists():
        raise FileNotFoundError(
            f'[{pier.pier_name}] Файл свай не найден: {pier.pile_mct_file_path!r}')

    return load_piles_from_mct(
        model=model,
        node_offset=pier.node_offset_piles,
        elem_offset=pier.elem_offset_piles,
        mct_path=str(mct_path),
    )


def load_pier_body_for_pier(model: PierModel, pier) -> Optional[MctLoadResult]:
    """
    Обёртка для вызова из generate_pier_geometry:
    читает mct_file_path из PierGeometry и загружает тело опоры в модель.

    Используется только для geom_source='mct'.
    Возвращает None если mct_file_path не задан.
    Выбрасывает FileNotFoundError если файл не найден.
    """
    from data_structures import PierGeometry  # локальный импорт избегает цикла
    assert isinstance(pier, PierGeometry)

    if not pier.mct_file_path:
        return None

    mct_path = Path(pier.mct_file_path)
    if not mct_path.exists():
        raise FileNotFoundError(
            f'[{pier.pier_name}] Файл тела опоры не найден: {pier.mct_file_path!r}')

    return load_pier_body_from_mct(
        model=model,
        node_offset=pier.node_offset_footing,
        elem_offset=pier.elem_offset_footing,
        mct_path=str(mct_path),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Тесты Части 3
# ═══════════════════════════════════════════════════════════════════════════════

def test_pile_part3(mct_path: str, node_offset: int = 1001, elem_offset: int = 1001) -> bool:
    """
    Автономный тест Части 3 на реальном .mct файле (свай).

    Проверяет:
      1. Количество узлов, элементов и пружин совпадает с тем, что в файле.
      2. Перенумерация узлов строго монотонна (нет дырок в диапазоне).
      3. Каждый элемент ссылается на существующие узлы модели.
      4. Для каждой пружины узел существует в модели.
      5. Порядок нумерации: первый узел имеет max X, max Y, max Z.

    Возвращает True если все проверки прошли.
    """
    model = PierModel(pier_name='__test__')
    result = load_piles_from_mct(model, node_offset, elem_offset, mct_path)

    ok = True
    checks: list[tuple[bool, str]] = []

    raw_nodes, raw_elements, raw_springs, _ = _parse_mct(mct_path)
    checks.append((result.n_nodes == len(raw_nodes),
                   f'узлов: добавлено {result.n_nodes}, в файле {len(raw_nodes)}'))
    checks.append((result.n_elements == len(raw_elements),
                   f'элементов: добавлено {result.n_elements}, в файле {len(raw_elements)}'))
    checks.append((result.n_springs == len(raw_springs),
                   f'пружин: добавлено {result.n_springs}, в файле {len(raw_springs)}'))

    pile_nids = sorted(nid for nid in model.nodes if nid >= node_offset)
    expected_range = list(range(node_offset, node_offset + result.n_nodes))
    checks.append((pile_nids == expected_range,
                   f'монотонность узлов: {pile_nids[:5]}... ожидалось {expected_range[:5]}...'))

    bad_refs = [
        eid for eid, e in model.elements.items()
        if e.node_i not in model.nodes or e.node_j not in model.nodes
    ]
    checks.append((not bad_refs, f'битые ссылки элементов: {bad_refs[:5]}'))

    bad_springs = [nid for nid in model.springs if nid not in model.nodes]
    checks.append((not bad_springs, f'пружины без узлов: {bad_springs[:5]}'))

    if raw_nodes:
        sorted_nodes = sorted(raw_nodes, key=_sort_key_for_node)
        first_raw = sorted_nodes[0]
        first_node = model.nodes.get(node_offset)
        if first_node:
            pos_ok = (
                abs(first_node.x - first_raw.x) < 1e-9 and
                abs(first_node.y - first_raw.y) < 1e-9 and
                abs(first_node.z - first_raw.z) < 1e-9
            )
            checks.append((pos_ok,
                            f'первый узел {node_offset}: '
                            f'({first_node.x}, {first_node.y}, {first_node.z}) '
                            f'ожидалось ({first_raw.x}, {first_raw.y}, {first_raw.z})'))

    print(f'\n  ТЕСТ Части 3 (сваи) [{mct_path}]:')
    for passed, desc in checks:
        mark = '✓' if passed else '✗'
        print(f'    {mark} {desc}')
        if not passed:
            ok = False

    if result.errors:
        print(f'    Предупреждения/ошибки парсинга ({len(result.errors)}):')
        for e in result.errors[:5]:
            print(f'      — {e}')

    print(f'    Итог: узлов={result.n_nodes}, элементов={result.n_elements}, '
          f'пружин={result.n_springs}')
    print(f'    Узлы id: {result.node_id_min}…{result.node_id_max}')
    print(f'    Элементы id: {result.elem_id_min}…{result.elem_id_max}')

    return ok


def test_pier_body_part3(mct_path: str, node_offset: int = 1, elem_offset: int = 1) -> bool:
    """
    Автономный тест загрузки тела опоры из .mct файла (geom_source='mct').

    Проверяет:
      1. Количество узлов, элементов и пружин совпадает с файлом.
      2. Каждый элемент ссылается на существующие узлы модели.
      3. Для каждой пружины узел существует в модели.
      4. id узлов начинаются с node_offset.
      5. Списки материалов и сечений непусты (если есть элементы).

    Возвращает True если все проверки прошли.
    """
    model = PierModel(pier_name='__test_body__')
    result = load_pier_body_from_mct(model, node_offset, elem_offset, mct_path)

    ok = True
    checks: list[tuple[bool, str]] = []

    raw_nodes, raw_elements, raw_springs, _ = _parse_mct(mct_path)

    checks.append((result.n_nodes == len(raw_nodes),
                   f'узлов: добавлено {result.n_nodes}, в файле {len(raw_nodes)}'))
    checks.append((result.n_elements == len(raw_elements),
                   f'элементов: добавлено {result.n_elements}, в файле {len(raw_elements)}'))
    checks.append((result.n_springs == len(raw_springs),
                   f'пружин: добавлено {result.n_springs}, в файле {len(raw_springs)}'))

    bad_refs = [
        eid for eid, e in model.elements.items()
        if e.node_i not in model.nodes or e.node_j not in model.nodes
    ]
    checks.append((not bad_refs, f'битые ссылки элементов: {bad_refs[:5]}'))

    bad_springs = [nid for nid in model.springs if nid not in model.nodes]
    checks.append((not bad_springs, f'пружины без узлов: {bad_springs[:5]}'))

    if result.n_nodes > 0:
        checks.append((result.node_id_min == node_offset,
                        f'node_id_min={result.node_id_min}, ожидалось {node_offset}'))

    if raw_elements:
        checks.append((bool(result.material_numbers),
                        f'материалы: {result.material_numbers}'))
        checks.append((bool(result.section_numbers),
                        f'сечения: {result.section_numbers}'))

    print(f'\n  ТЕСТ Части 3 (тело опоры) [{mct_path}]:')
    for passed, desc in checks:
        mark = '✓' if passed else '✗'
        print(f'    {mark} {desc}')
        if not passed:
            ok = False

    if result.errors:
        print(f'    Предупреждения/ошибки парсинга ({len(result.errors)}):')
        for e in result.errors[:5]:
            print(f'      — {e}')

    print(f'    Итог: узлов={result.n_nodes}, элементов={result.n_elements}, '
          f'пружин={result.n_springs}')
    print(f'    Узлы id: {result.node_id_min}…{result.node_id_max}')
    print(f'    Элементы id: {result.elem_id_min}…{result.elem_id_max}')
    print(f'    Материалы: {result.material_numbers}')
    print(f'    Сечения:   {result.section_numbers}')

    return ok


# ── Запуск теста напрямую ──────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'piles'
    path = sys.argv[2] if len(sys.argv) > 2 else 'o4_6.mct'

    if mode == 'body':
        passed = test_pier_body_part3(path)
    else:
        passed = test_pile_part3(path)

    sys.exit(0 if passed else 1)

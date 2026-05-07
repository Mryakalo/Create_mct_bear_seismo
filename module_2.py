"""
module_2.py — Модуль 2: генерация параметрической геометрии опоры

Часть 1 — Стержень (ростверк → стойка → ригель):
    Мешинг трёх частей вдоль оси Z, каждая со своими зонами сечений.
    Узлы на стыках частей не дублируются.
    Заполняет model.nodes, model.elements, model.ts_groups.
"""

from dataclasses import dataclass, field
from typing import Optional

from additional_functions import _coord_key
from data_structures import (
    BearingPlaneRow,
    PierGeometry, PierModel, FrameResult, ShaftPartResult,
)
from module_2_part_1 import generate_shaft
from module_2_part_2 import generate_frames
from module_2_part_3 import (
    load_piles_for_pier, load_pier_body_for_pier,
    PileLoadResult, MctLoadResult,
)
from module_2_part_4 import generate_part4, Part4Result


# ── Несимметричные подферменники ─────────────────────────────────────────────
# module_1.parse_frame_parameters читает из листа «Опоры»:
#   f{n}_r_pad_y → FrameParameters.pad_y_right  (+Y, правый подферменник)
#   f{n}_l_pad_y → FrameParameters.pad_y_left   (−Y, левый  подферменник, >0)
# Если колонки не заданы — оба равны f{n}_pad_y (симметричный режим).
# data_structures.FrameParameters должен содержать поля pad_y_right и pad_y_left.
# ─────────────────────────────────────────────────────────────────────────────

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
    # Результат Части 4 — RigidLink, Constraints, Hinges
    part4_result: Optional['Part4Result'] = None

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

        # ── Часть 4 — RigidLink, Constraints, Hinges ──────────────────────────
        part4_result = generate_part4(model, pier)

        return PierGeometryResult(
            pier_name=pier.pier_name,
            model=model,
            mct_body_result=mct_body_result,
            pile_result=pile_result,
            part4_result=part4_result,
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

    # ── Часть 4 — RigidLink, Constraints, Hinges ─────────────────────────────
    part4_result = generate_part4(model, pier)

    return PierGeometryResult(
        pier_name=pier.pier_name,
        model=model,
        shaft_parts=shaft_parts,
        frame_results=frame_results,
        pile_result=pile_result,
        part4_result=part4_result,
    )
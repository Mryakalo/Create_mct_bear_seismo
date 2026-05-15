# ═══════════════════════════════════════════════════════════════════════════════
#  Модуль 3, Часть 4 — вертикальное давление грунта на ростверк
# ═══════════════════════════════════════════════════════════════════════════════
"""
module_3_part_4.py — Вертикальная нагрузка от веса грунта на верхний узел ростверка.

Алгоритм:
  1. Из площади самого верхнего сечения ростверка вычитается площадь самого
     нижнего сечения стойки — получается «кольцевая» площадь грунта над ростверком.
  2. Нагрузка [тс] = площадь × γ_грунта × h_грунта (вес грунта над ростверком).
  3. Нагрузка прикладывается к верхнему узлу ростверка как вертикальная
     сосредоточенная сила (NODAL-LOAD, направление −Z, тс).
  4. Та же нагрузка переводится в массу по Z: m_Z = F / g [тс·с²/м]
     и прикладывается к тому же узлу как сейсмическая масса (MASS, компонента Z).
     Выдаётся предупреждение, что масса задана только по Z, и предлагается
     заполнить поле разжиженного грунта для горизонтальных компонент.

Входные данные берутся из:
  - PierGeometry   → footing_zones / column_zones (секции для определения площадей)
  - SoilInfluence  → soil_load_on_footing, soil_load_unit_weight, soil_load_height,
                     footing_area_sec{1,2}_{top,bottom}, column_area_sec1_{top,bottom}
  - PierGeometryResult.coord_index → поиск верхнего узла ростверка
  - ProjectParameters.gravity → g, м/с²

Площади сечений:
  - «Верхнее сечение ростверка» = площадь верхнего волокна самой верхней зоны
    ростверка = footing_area_sec{N}_{top}, где N = кол-во зон ростверка.
  - «Нижнее сечение стойки»     = площадь нижнего волокна первой зоны стойки
    = column_area_sec1_bottom.
"""

import warnings as _warnings_module
from dataclasses import dataclass, field
from typing import Optional

from additional_functions import _coord_key, _ELEM_TYPE_FOOTING
from data_structures import PierGeometry, SoilInfluence, PierModel


# ═══════════════════════════════════════════════════════════════════════════════
#  Структура результата
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SoilVerticalLoadResult:
    """
    Результат Части 4 Модуля 3 — вертикальное давление грунта на ростверк.

    Поля:
      pier_name         — имя опоры
      node_id           — id верхнего узла ростверка, к которому приложена нагрузка
      z_node            — Z-координата этого узла (= footing_z_top), м
      area_footing_top  — площадь верхнего волокна верхней зоны ростверка, м²
      area_column_bot   — площадь нижнего волокна нижней зоны стойки, м²
      net_area          — расчётная площадь (area_footing_top − area_column_bot), м²
      unit_weight       — удельный вес грунта γ, тс/м³
      height            — высота грунта над ростверком h, м
      force_z           — вертикальная нагрузка F = net_area × γ × h, тс
                          (приложена вниз по Z, знак минус при записи в .mct)
      mass_z            — сейсмическая масса по Z: m_Z = force_z / g, тс·с²/м
      gravity           — ускорение свободного падения g, м/с²
      warnings          — диагностические сообщения
      skipped           — True, если расчёт не выполнен (флаг не установлен или нет данных)
    """
    pier_name:        str
    node_id:          Optional[int]   = None
    z_node:           Optional[float] = None
    area_footing_top: Optional[float] = None
    area_column_bot:  Optional[float] = None
    net_area:         Optional[float] = None
    unit_weight:      Optional[float] = None
    height:           Optional[float] = None
    force_z:          Optional[float] = None
    mass_z:           Optional[float] = None
    gravity:          float           = 9.806
    warnings:         list[str]       = field(default_factory=list)
    skipped:          bool            = False


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════

def _footing_top_area(soil: SoilInfluence, pier: PierGeometry) -> Optional[float]:
    """
    Площадь верхнего волокна самой верхней зоны ростверка [м²].

    Зоны перечислены в footing_zones по возрастанию zone_z_top.
    Самая верхняя зона = последняя в списке.
    Соответствующее поле SoilInfluence:
      зона 1 → footing_area_sec1_top
      зона 2 → footing_area_sec2_top
    Если зона не заполнена — спускаемся на предыдущую.
    """
    if not pier.footing_zones:
        return None

    # Сортируем зоны по zone_z_top (на случай если порядок нарушен в данных)
    sorted_zones = sorted(pier.footing_zones, key=lambda z: z.zone_z_top)
    n_zones = len(sorted_zones)

    # Маппинг: индекс зоны → поле площади верхнего волокна
    area_top_fields = [
        soil.footing_area_sec1_top,
        soil.footing_area_sec2_top,
    ]

    # Начинаем с самой верхней зоны и идём вниз, пока не найдём заполненное поле
    for zone_idx in range(n_zones - 1, -1, -1):
        if zone_idx < len(area_top_fields):
            area = area_top_fields[zone_idx]
            if area is not None:
                return area

    return None


def _column_bottom_area(soil: SoilInfluence, pier: PierGeometry) -> Optional[float]:
    """
    Площадь нижнего волокна самой нижней зоны стойки [м²].

    Самая нижняя зона стойки = первая в отсортированном списке column_zones.
    Соответствующее поле SoilInfluence: column_area_sec1_bottom.
    """
    if not pier.column_zones:
        return None

    # Первая (нижняя) зона стойки → column_area_sec1_bottom
    return soil.column_area_sec1_bottom


def _find_footing_top_node(
    model: PierModel,
    pier: PierGeometry,
    coord_index: dict,
    warnings: list[str],
) -> tuple[Optional[int], Optional[float]]:
    """
    Находит верхний узел ростверка (x=0, y=0, z=footing_z_top).

    Возвращает (node_id, z_node) или (None, None) если узел не найден.
    Использует coord_index для быстрого поиска.
    """
    z_top = pier.footing_z_top
    if z_top is None:
        warnings.append(
            f'  ⚠  [{pier.pier_name}] footing_z_top не задан — '
            f'верхний узел ростверка не может быть определён'
        )
        return None, None

    key = _coord_key(0.0, 0.0, z_top)
    node_id = coord_index.get(key)

    if node_id is None:
        warnings.append(
            f'  ⚠  [{pier.pier_name}] Верхний узел ростверка не найден '
            f'в coord_index (x=0.0, y=0.0, z={z_top:.4f})'
        )
        return None, z_top

    return node_id, z_top


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция Части 4
# ═══════════════════════════════════════════════════════════════════════════════

def generate_soil_vertical_load(
    model: PierModel,
    pier: PierGeometry,
    soil: SoilInfluence,
    coord_index: dict,
    gravity: float = 9.806,
) -> SoilVerticalLoadResult:
    """
    Вычисляет вертикальную нагрузку от грунта на верхний узел ростверка
    и соответствующую сейсмическую массу по Z.

    Параметры
    ----------
    model       : PierModel        — КЭ-модель опоры (используется для поиска узлов)
    pier        : PierGeometry     — геометрия опоры (зоны, офсеты)
    soil        : SoilInfluence    — грунтовые параметры опоры
    coord_index : dict             — индекс координат {_coord_key → node_id}
    gravity     : float            — ускорение свободного падения g, м/с²

    Возвращает SoilVerticalLoadResult.
    Не печатает ничего — вывод делает main.

    Логика
    -------
    Если soil.soil_load_on_footing is False — возвращает результат с skipped=True.
    Если данные неполные — заполняет warnings и возвращает частичный результат.
    """
    result = SoilVerticalLoadResult(pier_name=pier.pier_name, gravity=gravity)

    # ── Проверяем флаг включения нагрузки ────────────────────────────────────
    if not soil.soil_load_on_footing:
        result.skipped = True
        return result

    # ── Площадь верхнего сечения ростверка ───────────────────────────────────
    area_footing_top = _footing_top_area(soil, pier)
    result.area_footing_top = area_footing_top
    if area_footing_top is None:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Площадь верхнего сечения ростверка '
            f'(footing_area_sec*_top) не задана — расчёт невозможен'
        )
        result.skipped = True
        return result

    # ── Площадь нижнего сечения стойки ───────────────────────────────────────
    area_column_bot = _column_bottom_area(soil, pier)
    result.area_column_bot = area_column_bot
    if area_column_bot is None:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Площадь нижнего сечения стойки '
            f'(column_area_sec1_bottom) не задана — расчёт невозможен'
        )
        result.skipped = True
        return result

    # ── Расчётная площадь грунта ──────────────────────────────────────────────
    net_area = area_footing_top - area_column_bot
    result.net_area = net_area
    if net_area <= 0.0:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Расчётная площадь грунта отрицательна или '
            f'равна нулю (S_рост.верх={area_footing_top:.4f} м², '
            f'S_стойки.низ={area_column_bot:.4f} м²). '
            f'Нагрузка не прикладывается.'
        )
        result.skipped = True
        return result

    # ── Параметры грунта ──────────────────────────────────────────────────────
    gamma = soil.soil_load_unit_weight
    h     = soil.soil_load_height
    result.unit_weight = gamma
    result.height      = h

    if gamma is None:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Удельный вес грунта '
            f'(soil_load_unit_weight) не задан — расчёт невозможен'
        )
        result.skipped = True
        return result

    if h is None:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Высота грунта над ростверком '
            f'(soil_load_height) не задана — расчёт невозможен'
        )
        result.skipped = True
        return result

    if h <= 0.0:
        result.warnings.append(
            f'  ℹ  [{pier.pier_name}] Высота грунта над ростверком h={h:.4f} м ≤ 0 — '
            f'нагрузка равна нулю, не прикладывается.'
        )
        result.skipped = True
        return result

    # ── Вертикальная нагрузка [тс] ────────────────────────────────────────────
    force_z = net_area * gamma * h   # положительное значение → давит вниз (−Z в MCT)
    result.force_z = force_z

    # ── Сейсмическая масса по Z [тс·с²/м] ────────────────────────────────────
    if gravity <= 0.0:
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Ускорение свободного падения g={gravity} ≤ 0 — '
            f'масса не может быть вычислена'
        )
        result.skipped = True
        return result

    mass_z = force_z / gravity
    result.mass_z = mass_z

    # ── Поиск верхнего узла ростверка ────────────────────────────────────────
    node_id, z_node = _find_footing_top_node(model, pier, coord_index, result.warnings)
    result.node_id = node_id
    result.z_node  = z_node

    if node_id is None:
        # Нагрузка вычислена, но узел не найден — skipped не ставим, данные сохраняем
        result.warnings.append(
            f'  ⚠  [{pier.pier_name}] Нагрузка вычислена (F={force_z:.4f} тс, '
            f'm_Z={mass_z:.6f} тс·с²/м), но узел не найден — '
            f'запись в .mct невозможна'
        )
        return result

    # ── Предупреждение о массе только по Z ───────────────────────────────────
    result.warnings.append(
        f'  ℹ  [{pier.pier_name}] ВНИМАНИЕ: масса от грунта над ростверком '
        f'(m_Z = {mass_z:.6f} тс·с²/м) приложена ТОЛЬКО по вертикали (Z). '
        f'Если требуется учесть горизонтальные инерционные усилия '
        f'(например, при разжижении грунта), заполните поле '
        f'«разжиженный грунт» (liquefaction_present / liquefaction_*) — '
        f'горизонтальные массы рассчитываются в Части 2 Модуля 3.'
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Генерация .mct-команд
# ═══════════════════════════════════════════════════════════════════════════════

def format_soil_vertical_load_mct(
    result: SoilVerticalLoadResult,
    load_case_name: str = 'SOIL_VERT',
) -> list[str]:
    """
    Формирует строки .mct-файла для нагрузки и массы от грунта над ростверком.

    Возвращает список строк (без завершающего переноса строки).
    Если result.skipped или node_id/force_z/mass_z не определены — возвращает
    список с комментарием.

    Формат нагрузки (*CONLOAD в Midas Civil):
      node_id, FX, FY, FZ, MX, MY, MZ
      Вертикальная нагрузка → FZ = −force_z (давит вниз).

    Формат массы (*MASS в Midas Civil):
      node_id, mX, mY, mZ  (здесь mX=0, mY=0, mZ=mass_z).
    """
    lines: list[str] = []

    if result.skipped or result.node_id is None:
        lines.append(
            f'; [{result.pier_name}] Вертикальная нагрузка грунта на ростверк: '
            f'не применяется (skipped={result.skipped})'
        )
        return lines

    if result.force_z is None or result.mass_z is None:
        lines.append(
            f'; [{result.pier_name}] Вертикальная нагрузка грунта: '
            f'данные неполные (force_z или mass_z не вычислены)'
        )
        return lines

    nid     = result.node_id
    force_z = result.force_z
    mass_z  = result.mass_z

    # ── *CONLOAD — сосредоточенная нагрузка ──────────────────────────────────
    lines.append(f'; [{result.pier_name}] Вертикальное давление грунта на ростверк')
    lines.append(f'; S_net={result.net_area:.4f} м², '
                 f'γ={result.unit_weight:.4f} тс/м³, '
                 f'h={result.height:.4f} м, '
                 f'F={force_z:.4f} тс → узел {nid}')
    lines.append('*CONLOAD')
    lines.append(f'; LoadCase={load_case_name}')
    # Формат Midas Civil: NODE_ID, FX, FY, FZ, MX, MY, MZ
    lines.append(
        f'   {nid}, 0.0, 0.0, {-force_z:.6f}, 0.0, 0.0, 0.0'
    )

    # ── *MASS — сейсмическая масса ────────────────────────────────────────────
    lines.append('')
    lines.append(f'; [{result.pier_name}] Масса от грунта над ростверком (только по Z)')
    lines.append(f'; m_Z = F/g = {force_z:.4f} / {result.gravity:.4f} '
                 f'= {mass_z:.6f} тс·с²/м → узел {nid}')
    lines.append('; ПРЕДУПРЕЖДЕНИЕ: масса задана только по компоненте Z.')
    lines.append('; Для горизонтальных компонент используйте поле «разжижение».')
    lines.append('*MASS')
    # Формат Midas Civil: NODE_ID, mX, mY, mZ
    lines.append(
        f'   {nid}, 0.0, 0.0, {mass_z:.6f}'
    )

    return lines


# ═══════════════════════════════════════════════════════════════════════════════
#  Печать отчёта (вызывается из main)
# ═══════════════════════════════════════════════════════════════════════════════

def print_soil_vertical_load_report(result: SoilVerticalLoadResult) -> None:
    """
    Печатает краткий отчёт о вертикальной нагрузке грунта на ростверк.
    Вызывается из main после generate_soil_vertical_load().
    """
    print(f'\n  ── Часть 4: Вертикальное давление грунта на ростверк [{result.pier_name}]')

    if result.skipped:
        print('     Расчёт не выполнен (флаг soil_load_on_footing=False или '
              'данные неполные).')
        for w in result.warnings:
            print(w)
        return

    # Исходные данные
    print(f'     S ростверка (верх верхней зоны) : '
          f'{result.area_footing_top:.4f} м²')
    print(f'     S стойки   (низ нижней зоны)    : '
          f'{result.area_column_bot:.4f} м²')
    print(f'     Расчётная площадь грунта         : '
          f'{result.net_area:.4f} м²')
    print(f'     γ грунта                         : '
          f'{result.unit_weight:.4f} тс/м³')
    print(f'     h грунта над ростверком          : '
          f'{result.height:.4f} м')
    print(f'     Вертикальная нагрузка F          : '
          f'{result.force_z:.4f} тс  (−Z, узел {result.node_id})')
    print(f'     Сейсмическая масса m_Z = F/g     : '
          f'{result.mass_z:.6f} тс·с²/м  (узел {result.node_id})')

    for w in result.warnings:
        print(w)

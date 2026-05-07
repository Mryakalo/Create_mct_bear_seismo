"""
module_4.py — Модуль 4: Аффинное преобразование моделей опор.

Применяет к каждой КЭ-модели опоры поворот вокруг оси Z и перенос
в глобальные координаты. Вызывается ПОСЛЕ Модуля 3.

Порядок шагов внутри преобразования:
  1. Поворот на rotate_angle_deg (CCW при взгляде сверху) вокруг Z.
  2. Перенос на (translate_x, translate_y, translate_z).
  3. Присвоение beta-угла всем вертикальным элементам.

Публичный API
-------------
  apply_module4(pier, model) -> Part5Result
      Выполняет преобразование одной опоры. Возвращает Part5Result.

  run_module4(piers_to_calc, pier_results) -> dict[str, Part5Result]
      Обрабатывает все расчётные опоры. Возвращает словарь результатов.

  print_module4_report(pier_name, result) -> None
      Выводит отчёт в консоль.
"""

from __future__ import annotations

from typing import Optional

from data_structures import PierGeometry, PierModel, Part5Result
from module_2 import PierGeometryResult
from module_2_part5 import apply_affine_transform, print_part5_report


# ═══════════════════════════════════════════════════════════════════════════════
#  Основная функция преобразования одной опоры
# ═══════════════════════════════════════════════════════════════════════════════

def apply_module4(pier: PierGeometry, model: PierModel) -> Part5Result:
    """
    Применяет аффинное преобразование к модели одной опоры.

    Вызывает apply_affine_transform из module_2_part5 и сохраняет
    result в pier_geom_result.part5_result.

    Parameters
    ----------
    pier  : PierGeometry — параметры опоры (translate_*, rotate_angle_deg)
    model : PierModel    — КЭ-модель опоры после Модулей 2 и 3

    Returns
    -------
    Part5Result — сводка о выполненном преобразовании
    """
    return apply_affine_transform(model, pier)


# ═══════════════════════════════════════════════════════════════════════════════
#  Обработка всех опор
# ═══════════════════════════════════════════════════════════════════════════════

def run_module4(
    piers_to_calc: list[PierGeometry],
    pier_results:  dict[str, PierGeometryResult],
) -> dict[str, Part5Result]:
    """
    Применяет аффинное преобразование ко всем расчётным опорам.

    Для каждой опоры из piers_to_calc:
      - проверяет наличие модели в pier_results
      - вызывает apply_module4
      - записывает Part5Result обратно в pier_geom_result.part5_result

    Parameters
    ----------
    piers_to_calc : список PierGeometry для расчёта
    pier_results  : словарь {pier_name → PierGeometryResult} из Модуля 2

    Returns
    -------
    dict[str, Part5Result] — результаты по именам опор
    """
    transform_results: dict[str, Part5Result] = {}

    for pier in piers_to_calc:
        geom_result = pier_results.get(pier.pier_name)
        if geom_result is None or geom_result.model is None:
            continue

        result = apply_module4(pier, geom_result.model)

        # Сохраняем результат обратно в PierGeometryResult, чтобы
        # mct_generator мог передать его в Модуль 5 (генерацию .mct)
        geom_result.part5_result = result
        transform_results[pier.pier_name] = result

    return transform_results


# ═══════════════════════════════════════════════════════════════════════════════
#  Вывод в консоль
# ═══════════════════════════════════════════════════════════════════════════════

def print_module4_report(pier_name: str, result: Part5Result) -> None:
    """
    Выводит отчёт об аффинном преобразовании одной опоры.

    Формат:
      — заголовок с именем опоры
      — угол поворота и вектор переноса
      — количество пересчитанных узлов и элементов с beta-углом
      — пометка «(тождественное)» если преобразование не применялось
    """
    SEP = '─' * 60

    print(f'\n  {SEP}')
    print(f'  Аффинное преобразование [{pier_name}]')
    print(f'  {SEP}')

    if not result.applied:
        print('    (преобразование тождественное — пропущено)')
        return

    tx, ty, tz = result.translate
    print(f'    {"Угол поворота CCW:":<30} {result.rotate_angle_deg:+.4f}°')
    print(f'    {"Перенос dx:":<30} {tx:+.4f} м')
    print(f'    {"Перенос dy:":<30} {ty:+.4f} м')
    print(f'    {"Перенос dz:":<30} {tz:+.4f} м')
    print(f'    {SEP}')
    print(f'    {"Пересчитано узлов:":<30} {result.n_nodes_transformed}')
    print(f'    {"Beta-угол присвоен элементам:":<30} {result.n_elems_beta_set}')

    if result.errors:
        print(f'\n    Ошибки ({len(result.errors)}):')
        for e in result.errors:
            print(f'      ERR: {e}')

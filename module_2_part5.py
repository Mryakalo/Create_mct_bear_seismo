"""
module_2_part5.py — Часть 5 модуля 2: аффинное преобразование

Применяет к модели опоры два последовательных действия:

  1. Поворот вокруг глобальной оси Z на rotate_angle_deg (CCW при взгляде сверху).
     Матрица поворота:
         x' =  x·cos(θ) − y·sin(θ)
         y' =  x·sin(θ) + y·cos(θ)
         z' =  z  (без изменений)

  2. Перенос на вектор (translate_x, translate_y, translate_z).
         x'' = x' + tx
         y'' = y' + ty
         z'' = z' + tz

  3. Бета-угол вертикальных элементов.
     Вертикальный элемент — тот, у которого оба узла имеют одинаковые x и y
     (с допуском _COORD_TOL). Таким элементам присваивается beta = rotate_angle_deg.
     Бета-угол хранится в новом поле Element.beta_angle (добавляется динамически).

Важные инварианты
-----------------
  - coord_index (если передан) пересчитывается по новым координатам узлов;
    старые ключи полностью удаляются и заменяются новыми.
  - Порядок: сначала поворот, затем перенос — т.е. rotate → translate.
  - Если rotate_angle_deg == 0.0 и все translate == 0.0, функция возвращает
    управление немедленно (fast-path), не трогая model.
  - SpringSupport координат не содержит (привязан к node_id) — пересчёт не нужен.
  - FrameRLS, RigidLink, Constraint — не содержат координат — пересчёт не нужен.

Публичный API
-------------
  apply_affine_transform(model, pier, coord_index=None) -> Part5Result
  print_part5_report(result) -> None

Тесты
-----
  run_all_tests() -> None   запускает встроенные юнит-тесты

Интеграция с generate_pier_geometry (module_2.py)
--------------------------------------------------
  Добавить в конец generate_pier_geometry(), перед return:

      from module_2_part5 import apply_affine_transform
      part5_result = apply_affine_transform(model, pier)

  И добавить part5_result в PierGeometryResult.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from data_structures import PierGeometry, PierModel, Node, Element, Part5Result
from additional_functions import _coord_key, _rotate_xy, _is_vertical_element

# ─────────────────────────────────────────────────────────────────────────────
_COORD_TOL = 1e-6   # допуск совпадения координат (м), унаследован из проекта
_VERT_TOL  = 1e-4   # допуск для определения вертикальности элемента (м)
                     # чуть крупнее _COORD_TOL, чтобы покрывать round-off при
                     # мешинге (разница Δx, Δy не должна превышать этого порога)



# ═══════════════════════════════════════════════════════════════════════════════
#  Основные шаги преобразования
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_rotation_and_translation(
        model: PierModel,
        cos_a: float,
        sin_a: float,
        tx: float,
        ty: float,
        tz: float,
        coord_index: Optional[dict],
) -> int:
    """
    Выполняет поворот + перенос всех узлов модели «на месте».

    Обновляет Node.x, Node.y, Node.z для каждого узла.
    Если передан coord_index — перестраивает его по новым координатам.

    Возвращает количество пересчитанных узлов.
    """
    if coord_index is not None:
        coord_index.clear()

    for node in model.nodes.values():
        # 1. Поворот
        xr, yr = _rotate_xy(node.x, node.y, cos_a, sin_a)
        # 2. Перенос
        node.x = xr + tx
        node.y = yr + ty
        node.z = node.z + tz

        if coord_index is not None:
            coord_index[_coord_key(node.x, node.y, node.z)] = node.node_id

    return len(model.nodes)


def _apply_beta_angles(model: PierModel, beta_deg: float) -> int:
    """
    Присваивает бета-угол всем вертикальным элементам модели.

    Бета-угол хранится в атрибуте Element.beta_angle.
    Если атрибут ещё не существует (Element — dataclass без этого поля),
    он добавляется динамически через setattr.

    Возвращает количество элементов, которым присвоен бета-угол.
    """
    n_set = 0
    for elem in model.elements.values():
        if _is_vertical_element(model, elem):
            setattr(elem, 'beta_angle', beta_deg)
            n_set += 1
    return n_set


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная точка входа
# ═══════════════════════════════════════════════════════════════════════════════

def apply_affine_transform(
        model: PierModel,
        pier: PierGeometry,
        coord_index: Optional[dict] = None,
) -> Part5Result:
    """
    Применяет аффинное преобразование ко всем узлам модели.

    Шаги (всегда в этом порядке):
      1. Поворот вокруг глобальной оси Z на pier.rotate_angle_deg (CCW).
      2. Перенос на (pier.translate_x, pier.translate_y, pier.translate_z).
      3. Присвоение beta = rotate_angle_deg всем вертикальным элементам.

    Parameters
    ----------
    model : PierModel
        Полностью собранная модель опоры (после Частей 1–4).
    pier : PierGeometry
        Параметры опоры с полями rotate_angle_deg, translate_{x,y,z}.
    coord_index : dict | None
        Общий индекс координат {coord_key → node_id}.
        Если передан — перестраивается по новым координатам.
        Если None — игнорируется (координатный индекс вне этой части не нужен).

    Returns
    -------
    Part5Result
        Сводка о выполненном преобразовании.
    """
    angle_deg = pier.rotate_angle_deg
    tx = pier.translate_x
    ty = pier.translate_y
    tz = pier.translate_z

    result = Part5Result(
        rotate_angle_deg=angle_deg,
        translate=(tx, ty, tz),
    )

    # Fast-path: нулевое преобразование — ничего не делаем
    _is_identity = (
        math.isclose(angle_deg, 0.0, abs_tol=1e-9) and
        math.isclose(tx, 0.0, abs_tol=1e-9) and
        math.isclose(ty, 0.0, abs_tol=1e-9) and
        math.isclose(tz, 0.0, abs_tol=1e-9)
    )
    if _is_identity:
        # Бета-угол = 0 по умолчанию: явно не устанавливаем, Midas Civil
        # интерпретирует отсутствующий атрибут как beta = 0.
        result.applied = False
        return result

    # ── Шаг 1–2: поворот + перенос узлов ────────────────────────────────────
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    result.n_nodes_transformed = _apply_rotation_and_translation(
        model, cos_a, sin_a, tx, ty, tz, coord_index,
    )

    # ── Шаг 3: бета-угол вертикальных элементов ──────────────────────────────
    # Проверка вертикальности корректна и после поворота: поворот вокруг Z
    # одинаково сдвигает оба узла элемента, поэтому Δx и Δy между ними
    # не меняются.
    if not math.isclose(angle_deg, 0.0, abs_tol=1e-9):
        result.n_elems_beta_set = _apply_beta_angles(model, angle_deg)

    result.applied = True
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Вывод в main
# ═══════════════════════════════════════════════════════════════════════════════

def print_part5_report(result: Part5Result) -> None:
    """Печатает сводку по аффинному преобразованию."""
    print('\n' + '═' * 60)
    print('  ЧАСТЬ 5 — Аффинное преобразование')
    print('═' * 60)

    if not result.applied:
        print('  (преобразование тождественное — пропущено)')
        print()
        return

    tx, ty, tz = result.translate
    print(f'  Угол поворота (CCW):  {result.rotate_angle_deg:+.4f}°')
    print(f'  Вектор переноса:      dx={tx:+.4f}  dy={ty:+.4f}  dz={tz:+.4f}  м')
    print(f'  Пересчитано узлов:    {result.n_nodes_transformed}')
    print(f'  Бета-угол присвоен:   {result.n_elems_beta_set} вертикальным элементам')

    if result.errors:
        print('\n  ⚠ ОШИБКИ:')
        for err in result.errors:
            print(f'    • {err}')

    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Юнит-тесты
# ═══════════════════════════════════════════════════════════════════════════════

def _make_simple_model() -> tuple[PierModel, PierGeometry]:
    """
    Строит минимальную модель для тестов.

    Узлы:
      1: (0, 0, 0)  — низ ростверка
      2: (0, 0, 2)  — верх ростверка (вертикальный элемент с узлом 1)
      3: (1, 0, 2)  — горизонтальный узел (ребро идёт к узлу 2, не вертикальное)

    Элементы:
      101: 1→2  (вертикальный)
      102: 2→3  (горизонтальный)
    """
    model = PierModel(pier_name='TEST')
    model.nodes[1] = Node(node_id=1, x=0.0, y=0.0, z=0.0)
    model.nodes[2] = Node(node_id=2, x=0.0, y=0.0, z=2.0)
    model.nodes[3] = Node(node_id=3, x=1.0, y=0.0, z=2.0)

    model.elements[101] = Element(
        elem_id=101, node_i=1, node_j=2,
        section_number=1, material_number=1,
    )
    model.elements[102] = Element(
        elem_id=102, node_i=2, node_j=3,
        section_number=1, material_number=1,
    )

    pier = PierGeometry(
        pier_name='TEST',
        rotate_angle_deg=0.0,
        translate_x=0.0,
        translate_y=0.0,
        translate_z=0.0,
    )
    return model, pier


# ── Тест 1: тождественное преобразование ─────────────────────────────────────

def test_identity_transform() -> bool:
    """При нулевом угле и нулевом переносе координаты не меняются."""
    model, pier = _make_simple_model()
    original_coords = {nid: (n.x, n.y, n.z) for nid, n in model.nodes.items()}

    result = apply_affine_transform(model, pier)

    ok_applied = not result.applied
    ok_coords = all(
        math.isclose(model.nodes[nid].x, cx, abs_tol=1e-9) and
        math.isclose(model.nodes[nid].y, cy, abs_tol=1e-9) and
        math.isclose(model.nodes[nid].z, cz, abs_tol=1e-9)
        for nid, (cx, cy, cz) in original_coords.items()
    )

    ok = ok_applied and ok_coords
    print(f'  ТЕСТ 1 (тождественное преобразование): {"✓" if ok else "✗"}')
    return ok


# ── Тест 2: перенос без поворота ─────────────────────────────────────────────

def test_translation_only() -> bool:
    """Перенос: все узлы сдвигаются на (dx, dy, dz)."""
    model, pier = _make_simple_model()
    pier.translate_x = 10.0
    pier.translate_y = 5.0
    pier.translate_z = 3.0

    apply_affine_transform(model, pier)

    n1 = model.nodes[1]
    ok = (
        math.isclose(n1.x, 10.0, abs_tol=1e-9) and
        math.isclose(n1.y,  5.0, abs_tol=1e-9) and
        math.isclose(n1.z,  3.0, abs_tol=1e-9)
    )
    n3 = model.nodes[3]
    ok &= (
        math.isclose(n3.x, 11.0, abs_tol=1e-9) and
        math.isclose(n3.y,  5.0, abs_tol=1e-9) and
        math.isclose(n3.z,  5.0, abs_tol=1e-9)
    )

    print(f'  ТЕСТ 2 (перенос без поворота): {"✓" if ok else "✗"}')
    return ok


# ── Тест 3: поворот на 90° ───────────────────────────────────────────────────

def test_rotation_90() -> bool:
    """
    Поворот на 90° CCW:
      (1, 0) → (0, 1)
      (0, 1) → (−1, 0)
      (0, 0) → (0, 0)
    """
    model, pier = _make_simple_model()
    pier.rotate_angle_deg = 90.0

    apply_affine_transform(model, pier)

    n3 = model.nodes[3]   # исходно (1, 0, 2) → (0, 1, 2)
    ok = (
        math.isclose(n3.x,  0.0, abs_tol=1e-9) and
        math.isclose(n3.y,  1.0, abs_tol=1e-9) and
        math.isclose(n3.z,  2.0, abs_tol=1e-9)
    )

    n1 = model.nodes[1]   # (0,0,0) остаётся (0,0,0)
    ok &= (
        math.isclose(n1.x, 0.0, abs_tol=1e-9) and
        math.isclose(n1.y, 0.0, abs_tol=1e-9)
    )

    print(f'  ТЕСТ 3 (поворот 90°): {"✓" if ok else "✗"}')
    return ok


# ── Тест 4: поворот + перенос (порядок имеет значение) ───────────────────────

def test_rotate_then_translate() -> bool:
    """
    Поворот выполняется ДО переноса.
    Точка (1, 0) при повороте 90° → (0, 1), затем перенос (+1, +1) → (1, 2).
    """
    model, pier = _make_simple_model()
    pier.rotate_angle_deg = 90.0
    pier.translate_x = 1.0
    pier.translate_y = 1.0
    pier.translate_z = 0.0

    apply_affine_transform(model, pier)

    n3 = model.nodes[3]   # (1,0,2) → rotate → (0,1,2) → translate → (1,2,2)
    ok = (
        math.isclose(n3.x, 1.0, abs_tol=1e-9) and
        math.isclose(n3.y, 2.0, abs_tol=1e-9) and
        math.isclose(n3.z, 2.0, abs_tol=1e-9)
    )

    print(f'  ТЕСТ 4 (поворот → перенос): {"✓" if ok else "✗"}')
    return ok


# ── Тест 5: бета-угол присваивается только вертикальным ──────────────────────

def test_beta_only_vertical() -> bool:
    """
    Элемент 101 (узлы с одинаковыми x, y) → вертикальный → beta присваивается.
    Элемент 102 (узлы с разными x) → горизонтальный → beta НЕ присваивается.
    """
    model, pier = _make_simple_model()
    pier.rotate_angle_deg = 45.0

    apply_affine_transform(model, pier)

    e101 = model.elements[101]
    e102 = model.elements[102]

    ok_vert  = hasattr(e101, 'beta_angle') and math.isclose(e101.beta_angle, 45.0, abs_tol=1e-9)
    ok_horiz = not hasattr(e102, 'beta_angle') or not math.isclose(
        getattr(e102, 'beta_angle', 999.0), 45.0, abs_tol=1e-9)

    ok = ok_vert and ok_horiz
    print(f'  ТЕСТ 5 (бета только у вертикальных): {"✓" if ok else "✗"}'
          f'  (e101.beta={getattr(e101, "beta_angle", "—")}, '
          f'e102.beta={getattr(e102, "beta_angle", "—")})')
    return ok


# ── Тест 6: coord_index пересчитывается ──────────────────────────────────────

def test_coord_index_rebuilt() -> bool:
    """
    После преобразования coord_index содержит новые ключи, совпадающие
    с новыми координатами узлов.
    """
    model, pier = _make_simple_model()
    pier.translate_x = 5.0

    coord_index: dict = {}
    for n in model.nodes.values():
        coord_index[_coord_key(n.x, n.y, n.z)] = n.node_id

    apply_affine_transform(model, pier, coord_index=coord_index)

    # Ключ узла 1 после переноса: (5, 0, 0)
    expected_key = _coord_key(5.0, 0.0, 0.0)
    ok = (coord_index.get(expected_key) == 1)

    # Старого ключа (0,0,0) быть не должно
    old_key = _coord_key(0.0, 0.0, 0.0)
    ok &= (old_key not in coord_index)

    print(f'  ТЕСТ 6 (coord_index пересчитан): {"✓" if ok else "✗"}')
    return ok


# ── Тест 7: count_report — n_nodes_transformed и n_elems_beta_set ────────────

def test_result_counts() -> bool:
    """
    Part5Result.n_nodes_transformed == 3 (все узлы модели).
    Part5Result.n_elems_beta_set    == 1 (только вертикальный элемент 101).
    """
    model, pier = _make_simple_model()
    pier.rotate_angle_deg = 30.0
    pier.translate_x = 1.0

    result = apply_affine_transform(model, pier)

    ok_nodes = (result.n_nodes_transformed == 3)
    ok_beta  = (result.n_elems_beta_set == 1)
    ok = ok_nodes and ok_beta

    print(f'  ТЕСТ 7 (счётчики результата): {"✓" if ok else "✗"}'
          f'  (n_nodes={result.n_nodes_transformed}, n_beta={result.n_elems_beta_set})')
    return ok


# ── Тест 8: поворот на 360° = тождественное преобразование (численно) ────────

def test_rotation_360_is_identity() -> bool:
    """Поворот на 360° (± 1е-9) возвращает координаты к исходным."""
    model, pier = _make_simple_model()
    original = {nid: (n.x, n.y, n.z) for nid, n in model.nodes.items()}
    pier.rotate_angle_deg = 360.0

    apply_affine_transform(model, pier)

    ok = all(
        math.isclose(model.nodes[nid].x, cx, abs_tol=1e-9) and
        math.isclose(model.nodes[nid].y, cy, abs_tol=1e-9) and
        math.isclose(model.nodes[nid].z, cz, abs_tol=1e-9)
        for nid, (cx, cy, cz) in original.items()
    )

    print(f'  ТЕСТ 8 (поворот 360° ≈ тождественный): {"✓" if ok else "✗"}')
    return ok


def run_all_tests() -> None:
    """Запускает все тесты Части 5 и выводит итог."""
    print('\n' + '─' * 60)
    print('  Запуск тестов Части 5')
    print('─' * 60)

    tests = [
        test_identity_transform,
        test_translation_only,
        test_rotation_90,
        test_rotate_then_translate,
        test_beta_only_vertical,
        test_coord_index_rebuilt,
        test_result_counts,
        test_rotation_360_is_identity,
    ]

    results = [t() for t in tests]
    n_pass = sum(results)
    n_total = len(results)

    print('─' * 60)
    print(f'  Итог: {n_pass}/{n_total} тестов пройдено '
          f'{"✓ ВСЕ" if n_pass == n_total else "✗ ЕСТЬ ОШИБКИ"}')
    print('─' * 60)


# ═══════════════════════════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    run_all_tests()

    # ── Демонстрация ──────────────────────────────────────────────────────────
    print('\n' + '═' * 60)
    print('  Демонстрация: поворот 30° + перенос (10, 5, 3)')

    demo_model, demo_pier = _make_simple_model()
    demo_pier.rotate_angle_deg = 30.0
    demo_pier.translate_x = 10.0
    demo_pier.translate_y = 5.0
    demo_pier.translate_z = 3.0

    print('\n  Координаты ДО:')
    for n in demo_model.nodes.values():
        print(f'    #{n.node_id}: ({n.x:.4f}, {n.y:.4f}, {n.z:.4f})')

    demo_result = apply_affine_transform(demo_model, demo_pier)

    print('\n  Координаты ПОСЛЕ:')
    for n in demo_model.nodes.values():
        beta = getattr(demo_model.elements.get(
            next((eid for eid, e in demo_model.elements.items()
                  if e.node_i == n.node_id or e.node_j == n.node_id), None)
            or 0, None), 'beta_angle', None)
        print(f'    #{n.node_id}: ({n.x:.4f}, {n.y:.4f}, {n.z:.4f})')

    print('\n  Бета-углы элементов:')
    for eid, elem in demo_model.elements.items():
        beta = getattr(elem, 'beta_angle', '—')
        print(f'    #{eid}: beta = {beta}')

    print_part5_report(demo_result)

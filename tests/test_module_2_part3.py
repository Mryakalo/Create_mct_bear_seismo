# ═══════════════════════════════════════════════════════════════════════════════
#  Тесты Части 3
# ═══════════════════════════════════════════════════════════════════════════════
from data_structures import PierModel
from module_2_part3 import load_piles_from_mct, _parse_mct, _sort_key_for_node, load_pier_body_from_mct


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
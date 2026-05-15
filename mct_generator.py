"""
mct_generator.py — генератор .mct файлов Midas Civil
Расчёт опор моста на сейсмическое воздействие по СП 268.1325800.2016

Запуск:
    python mct_generator.py seismic_input.xlsx [папка_вывода]

Выходные файлы:
    {pier_name}_no_temp.mct   — без временной нагрузки
    {pier_name}_with_temp.mct — с временной нагрузкой
"""

import sys

from module_1 import read_all_input_data, validate_input_data
import math

from module_2 import (
    generate_pier_geometry,
    PierGeometryResult,
    _part_label,
)

from module_2_part_4 import print_part4_report

from module_3_part1 import (
    build_all_load_assignments,
    print_module3_report,
    PierLoadAssignment,
)

from module_3_part2 import (
    build_all_fluid_masses,
    print_fluid_masses_report,
    FluidMassResult,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Функции вывода результатов Модуля 2 в консоль
# ═══════════════════════════════════════════════════════════════════════════════

# Ширины столбцов для таблицы стержня
_COL_SHAFT = {
    'elem':    7,
    'node_i':  8,
    'node_j':  8,
    'part':   10,
    'length': 10,
    'sec':     7,
    'mat':     8,
}

# Ширины столбцов для таблицы рамок
_COL_FRAME = {
    'elem':    7,
    'node_i':  8,
    'node_j':  8,
    'part':   34,   # расширено с 30 до 34 для меток вида «Горизонталь z_road (−Y→ось)»
    'length': 10,
    'sec':     7,
    'mat':     8,
}

# Ширины столбцов для таблицы координат узлов рамки
_COL_NODES = {
    'node_id':  6,
    'role':     5,
    'x':       11,
    'y':       11,
    'z':       12,
    'part':    34,
}


def _table_header(col_widths: dict, header_cells: list[str], title: str) -> None:
    sep = '─'
    widths  = list(col_widths.values())
    total_w = sum(widths) + len(widths) * 3 - 1
    headers = ' | '.join(c.center(w) for c, w in zip(header_cells, widths))
    line    = sep * total_w
    print(f'\n    {title:^{total_w}}')
    print(f'    {line}')
    print(f'    {headers}')
    print(f'    {line}')
    return total_w, line


def print_shaft_report(result: PierGeometryResult) -> None:
    """
    Выводит в консоль отчёт по стержню опоры:
      — сводка по частям (длина, узлы, элементы)
      — таблица элементов стержня
    """
    model = result.model
    if model is None:
        print(f'  Опора [{result.pier_name}]: модель не построена — пропуск')
        return

    print(f'\n  Опора [{result.pier_name}] — стержень:')
    for sp in result.shaft_parts:
        length = sp.z_top - sp.z_bottom
        print(f'    {sp.name:10s}: Z={sp.z_bottom:.3f}…{sp.z_top:.3f} м  '
              f'L={length:.3f} м  узлов={sp.n_nodes}  элементов={sp.n_elems}')

    print(f'    {"─"*50}')
    print(f'    Итого по опоре: узлов={len(model.nodes)}, '
          f'элементов={len(model.elements)}, '
          f'TS-групп={len(model.ts_groups)}')

    # Таблица элементов стержня
    offsets = {sp.name: sp.elem_offset for sp in result.shaft_parts}
    header_cells = ['№ эл.', 'Узел i', 'Узел j', 'Часть', 'Длина, м', 'Сечение', 'Материал']
    total_w, line = _table_header(_COL_SHAFT, header_cells, 'Таблица элементов стержня')

    shaft_elem_ids = set()
    for sp in result.shaft_parts:
        for eid in model.elements:
            if eid >= sp.elem_offset:
                shaft_elem_ids.add(eid)
    # Ограничиваем только элементами стержня (до первого офсета рамок)
    frame_offsets = [
        e for e in [
            getattr(result, 'frame_results', []),
        ]
    ]
    # Надёжнее: выбираем элементы, чей id попадает в диапазон стержня
    min_frame_off = min(
        (fr.elem_labels[0][0] for fr in result.frame_results if fr.elem_labels),
        default=10**9,
    )
    shaft_eids = sorted(eid for eid in model.elements if eid < min_frame_off)

    widths = list(_COL_SHAFT.values())
    for eid in shaft_eids:
        elem   = model.elements[eid]
        ni     = model.nodes[elem.node_i]
        nj     = model.nodes[elem.node_j]
        length = abs(nj.z - ni.z)
        part   = _part_label(eid, offsets)
        cells  = [
            str(eid)                   .rjust(widths[0]),
            str(elem.node_i)           .rjust(widths[1]),
            str(elem.node_j)           .rjust(widths[2]),
            part                       .ljust(widths[3]),
            f'{length:.4f}'            .rjust(widths[4]),
            str(elem.section_number)   .rjust(widths[5]),
            str(elem.material_number)  .rjust(widths[6]),
        ]
        print(f'    {" | ".join(cells)}')

    print(f'    {line}')
    print(f'    Итого элементов стержня: {len(shaft_eids)}')


# ───────────────────────────────────────────────────────────────────────────────
#  Вспомогательные функции для вывода координат узлов рамки
# ───────────────────────────────────────────────────────────────────────────────

def _print_node_coords_table(model, elem_labels: list[tuple[int, str]]) -> None:
    """
    Выводит таблицу координат узлов всех элементов рамки.

    Узлы сгруппированы по элементам в порядке elem_labels
    (подферменники → ОЧ → вертикали → горизонтали).
    Каждый уникальный узел печатается с полными координатами один раз;
    при повторном появлении выводится пометка «← уже выведен».
    """
    DOT_SEP = '·' * 76
    DASH_SEP = '─' * 76

    widths = list(_COL_NODES.values())
    header_cells = ['Узел', 'Роль', 'x, м', 'y, м', 'z, м', 'Часть элемента']
    headers = ' | '.join(c.center(w) for c, w in zip(header_cells, widths))

    print(f'\n    Координаты узлов рамки:')
    print(f'    {DOT_SEP}')
    print(f'    {headers}')
    print(f'    {DOT_SEP}')

    seen: set[int] = set()

    for eid, sublabel in elem_labels:
        elem = model.elements[eid]

        print(f'    {DASH_SEP}')
        print(f'    Элемент {eid}  |  {sublabel}')

        for node_id, role in ((elem.node_i, 'i'), (elem.node_j, 'j')):
            if node_id not in model.nodes:
                print(f'    {str(node_id).rjust(widths[0])} | {role.center(widths[1])} | '
                      f'{"(узел отсутствует в модели)"}')
                continue

            node   = model.nodes[node_id]
            suffix = '  ← уже выведен' if node_id in seen else ''
            x_str = f'{node.x:.4f}'
            y_str = f'-{abs(node.y):.4f}' if node.y < 0 else f'+{node.y:.4f}'
            z_str = f'{node.z:.4f}'
            cells  = [
                str(node_id)  .rjust(widths[0]),
                role          .center(widths[1]),
                x_str         .rjust(widths[2]),
                y_str         .rjust(widths[3]),
                z_str         .rjust(widths[4]),
                sublabel      .ljust(widths[5]),
            ]
            print(f'    {" | ".join(cells)}{suffix}')
            seen.add(node_id)

    print(f'    {DOT_SEP}')
    print(f'    Уникальных узлов рамки: {len(seen)}')


def print_frames_report(result: PierGeometryResult) -> None:
    """
    Выводит в консоль отчёт по рамкам опоры:
      — заголовок: кол-во рамок, режим
      — для каждой рамки:
          · отметки шарнира, ЦТ, проезжей части
          · параметры подферменников
          · параметры каждой опорной части (позиция X/Y, Z-диапазон, тип)
          · размеры вертикалей и горизонталей
          · таблица элементов рамки
          · таблица координат узлов (подферменники, ОЧ, вертикали, горизонтали)
    """
    model = result.model
    if model is None or not result.frame_results:
        return

    n_frames   = len(result.frame_results)
    mode_label = 'with_temp' if result.frame_results[0].include_temp else 'no_temp'
    print(f'\n  {"═"*58}')
    print(f'  Рамки опоры [{result.pier_name}] — {n_frames} рамок ({mode_label})')
    print(f'  {"═"*58}')

    for fr in result.frame_results:
        print(f'\n    ── Рамка {fr.frame_number}  '
              f'(X={fr.x_coordinate:.3f} м) ──────────────────────────')

        # ── Отметки ──────────────────────────────────────────────────────────
        print(f'    Отметки:')
        print(f'      z_hinge = {fr.z_hinge:.3f} м  (верх опорной части / шарнир)')
        print(f'      z_cg    = {fr.z_cg:.3f} м  (ЦТ пролётного строения)')
        print(f'      z_road  = {fr.z_road:.3f} м  (верх проезжей части)')

        # ── Подферменники ────────────────────────────────────────────────────
        h_pad = fr.pad_z_top - fr.pad_z_bottom
        asymmetric = abs(fr.pad_y_right - fr.pad_y_left) > 1e-6
        if asymmetric:
            print(f'    Подферменники (несимметрично):')
            print(f'      X = {fr.x_coordinate:.3f} м  |  '
                  f'+Y = {fr.pad_y_right:.3f} м  |  −Y = {fr.pad_y_left:.3f} м')
        else:
            print(f'    Подферменники (×2, симметрично ±Y):')
            print(f'      X = {fr.x_coordinate:.3f} м  |  ±Y = {fr.pad_y_right:.3f} м')
        print(f'      Z: {fr.pad_z_bottom:.3f} → {fr.pad_z_top:.3f} м  '
              f'(h = {h_pad:.3f} м)')
        print(f'      сечение={fr.pad_section}  материал={fr.pad_material}')

        # ── Опорные части ────────────────────────────────────────────────────
        print(f'    Опорные части:')
        for bm in fr.bearing_metas:
            bn_str  = f'№{bm.bn}' if bm.bn is not None else '(№ не задан)'
            mov_str = []
            if bm.type_x == 'movable': mov_str.append('подвижная по X')
            if bm.type_y == 'movable': mov_str.append('подвижная по Y')
            type_str = ', '.join(mov_str) if mov_str else 'неподвижная'
            print(f'      {bm.side}  ОЧ {bn_str}  — {type_str}')
            print(f'        X = {bm.x:.3f} м  |  Y = {bm.y:+.3f} м')
            print(f'        Z: {bm.z_bot:.3f} → {bm.z_top:.3f} м  '
                  f'(h = {bm.height:.3f} м)')
            print(f'        сечение={fr.bearing_section}  '
                  f'материал={fr.bearing_material}')

        # ── Вертикали ────────────────────────────────────────────────────────
        h_v1 = fr.z_cg - fr.z_hinge
        h_v2 = fr.z_road - fr.z_cg
        print(f'    Вертикали z_hinge → z_cg (×2):')
        print(f'      Z: {fr.z_hinge:.3f} → {fr.z_cg:.3f} м  (h = {h_v1:.3f} м)')
        print(f'      сечение={fr.frame_section}  материал={fr.frame_material}')
        print(f'    Вертикали z_cg → z_road (×2, всегда):')
        print(f'      Z: {fr.z_cg:.3f} → {fr.z_road:.3f} м  (h = {h_v2:.3f} м)')
        print(f'      сечение={fr.frame_section}  материал={fr.frame_material}')

        # ── Горизонтали ──────────────────────────────────────────────────────
        r_half = fr.pad_y_right
        l_half = fr.pad_y_left
        print(f'    Горизонталь на z_cg = {fr.z_cg:.3f} м (2 сегмента, всегда):')
        print(f'      Y: {-l_half:+.3f} → 0.000 → {+r_half:+.3f} м')
        print(f'    Горизонталь на z_road = {fr.z_road:.3f} м (2 сегмента, всегда):')
        print(f'      Y: {-l_half:+.3f} → 0.000 → {+r_half:+.3f} м')

        # ── Итог по рамке ────────────────────────────────────────────────────
        print(f'    → новых узлов = {fr.n_nodes},  '
              f'новых элементов = {fr.n_elems}')

        # ── Таблица элементов рамки ──────────────────────────────────────────
        header_cells = ['№ эл.', 'Узел i', 'Узел j', 'Часть рамки',
                        'Длина, м', 'Сечение', 'Материал']
        total_w, line = _table_header(
            _COL_FRAME, header_cells,
            f'Таблица элементов рамки {fr.frame_number}',
        )
        widths = list(_COL_FRAME.values())
        for eid, sublabel in fr.elem_labels:
            elem   = model.elements[eid]
            ni     = model.nodes[elem.node_i]
            nj     = model.nodes[elem.node_j]
            length = math.sqrt(
                (nj.x - ni.x) ** 2 +
                (nj.y - ni.y) ** 2 +
                (nj.z - ni.z) ** 2
            )
            cells = [
                str(eid)                   .rjust(widths[0]),
                str(elem.node_i)           .rjust(widths[1]),
                str(elem.node_j)           .rjust(widths[2]),
                sublabel                   .ljust(widths[3]),
                f'{length:.4f}'            .rjust(widths[4]),
                str(elem.section_number)   .rjust(widths[5]),
                str(elem.material_number)  .rjust(widths[6]),
            ]
            print(f'    {" | ".join(cells)}')
        print(f'    {line}')
        print(f'    Итого элементов рамки: {len(fr.elem_labels)}')

        # ── Координаты узлов рамки ───────────────────────────────────────────
        _print_node_coords_table(model, fr.elem_labels)


def print_mct_body_report(result: PierGeometryResult) -> None:
    """
    Выводит в консоль отчёт по опоре, геометрия которой загружена из .mct файла.
    """
    r = result.mct_body_result
    if r is None:
        return

    sep = '─' * 58
    print(f'\n  Опора [{result.pier_name}] — геометрия из .mct файла:')
    print(f'    Файл: {r.mct_path}')

    if not result.model or (r.n_nodes == 0 and r.n_elements == 0):
        print(f'    ОШИБКА: модель не построена')
        for e in r.errors:
            print(f'      — {e}')
        return

    print(f'    {sep}')
    print(f'    {"Узлы":.<30} {r.n_nodes}')
    print(f'    {"Элементы":.<30} {r.n_elements}')
    print(f'    {"Пружины":.<30} {r.n_springs}')
    print(f'    {sep}')

    node_range = (f'{r.node_id_min}…{r.node_id_max}'
                  if r.node_id_min is not None else 'нет')
    elem_range = (f'{r.elem_id_min}…{r.elem_id_max}'
                  if r.elem_id_min is not None else 'нет')
    print(f'    {"Диапазон id узлов":.<30} {node_range}')
    print(f'    {"Диапазон id элементов":.<30} {elem_range}')
    print(f'    {sep}')

    mats = ', '.join(str(m) for m in r.material_numbers) if r.material_numbers else '—'
    secs = ', '.join(str(s) for s in r.section_numbers) if r.section_numbers else '—'
    print(f'    {"Номера материалов":.<30} {mats}')
    print(f'    {"Номера сечений":.<30} {secs}')

    if r.errors:
        print(f'    {sep}')
        print(f'    Предупреждения/ошибки ({len(r.errors)}):')
        for e in r.errors[:10]:
            print(f'      — {e}')
        if len(r.errors) > 10:
            print(f'      … ещё {len(r.errors) - 10} предупреждений')


def print_pile_report(result: PierGeometryResult) -> None:
    """
    Выводит в консоль отчёт по сваям опоры, загруженным из .mct файла.
    """
    pr = result.pile_result
    if pr is None:
        return

    sep = '─' * 58
    print(f'\n  Опора [{result.pier_name}] — сваи из .mct файла:')
    print(f'    Файл: {pr.mct_path}')

    if pr.n_nodes == 0 and pr.n_elements == 0:
        print(f'    ОШИБКА: сваи не загружены')
        for e in pr.errors:
            print(f'      — {e}')
        return

    print(f'    {sep}')
    print(f'    {"Узлы свай":.<30} {pr.n_nodes}')
    print(f'    {"Элементы свай":.<30} {pr.n_elements}')
    print(f'    {"Пружины (грунт)":.<30} {pr.n_springs}')
    print(f'    {sep}')

    node_range = (f'{pr.node_id_min}…{pr.node_id_max}'
                  if pr.node_id_min is not None else 'нет')
    elem_range = (f'{pr.elem_id_min}…{pr.elem_id_max}'
                  if pr.elem_id_min is not None else 'нет')
    print(f'    {"Диапазон id узлов":.<30} {node_range}')
    print(f'    {"Диапазон id элементов":.<30} {elem_range}')
    print(f'    {sep}')

    mats = ', '.join(str(m) for m in pr.material_numbers) if pr.material_numbers else '—'
    secs = ', '.join(str(s) for s in pr.section_numbers) if pr.section_numbers else '—'
    print(f'    {"Номера материалов":.<30} {mats}')
    print(f'    {"Номера сечений":.<30} {secs}')

    if pr.errors:
        print(f'    {sep}')
        print(f'    Предупреждения/ошибки ({len(pr.errors)}):')
        for e in pr.errors[:10]:
            print(f'      — {e}')
        if len(pr.errors) > 10:
            print(f'      … ещё {len(pr.errors) - 10} предупреждений')


# ═══════════════════════════════════════════════════════════════════════════════
#  Точка входа
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # Для запуска из IDE раскомментируйте и укажите путь:
    # sys.argv = ['mct_generator.py', r'D:\путь\к\seismic_input.xlsx']

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    excel_file_path = sys.argv[1]
    print(f'Читаем: {excel_file_path}\n')

    # ── Модуль 1: чтение входных данных ─────────────────────────────────────
    print('\n' + '═' * 60)
    print('Модуль 1 — чтение входных данных')
    print('═' * 60)

    all_data = read_all_input_data(excel_file_path)
    project  = all_data['project']

    print(f'Проект:  {project.project_name}')
    print(f'g = {project.gravity} м/с²,  μ = {project.friction_coefficient}')
    print()

    print(f'Плети ({len(all_data["plety"])} строк):')
    for plety_row in all_data['plety']:
        print(f'  [{plety_row.span_group_name}] {plety_row.pier_name}: '
              f'z_hinge={plety_row.z_hinge_elevation}, '
              f'правая_ОЧ={plety_row.right_bearing_type_X}, '
              f'левая_ОЧ={plety_row.left_bearing_type_X}')
    print()

    print(f'Массы ({len(all_data["masses"])} строк):')
    for mass_row in all_data['masses']:
        print(f'  {mass_row.pier_name} (правая ОЧ №{mass_row.right_bearing_number}): '
              f'mX_прав_пост={mass_row.right_mass_X_permanent:.4f}, '
              f'mY_прав_пост={mass_row.right_mass_Y_permanent:.4f}, '
              f'mZ_прав_пост={mass_row.right_mass_Z_permanent:.4f}, '
              f'mX_прав_врем={mass_row.right_mass_X_temporary:.4f}, '
              f'mY_прав_врем={mass_row.right_mass_Y_temporary:.4f}, '
              f'mZ_прав_врем={mass_row.right_mass_Z_temporary:.4f}, ')
        print(
              f'     (левая ОЧ №{mass_row.left_bearing_number}): '
              f'mX_лев_пост={mass_row.left_mass_X_permanent:.4f}, '
              f'mY_лев_пост={mass_row.left_mass_Y_permanent:.4f}, '
              f'mZ_лев_пост={mass_row.left_mass_Z_permanent:.4f}, '
              f'mX_лев_врем={mass_row.left_mass_X_temporary:.4f}, '
              f'mY_лев_врем={mass_row.left_mass_Y_temporary:.4f}, '
              f'mZ_лев_врем={mass_row.left_mass_Z_temporary:.4f}, '
              )
    print()

    all_piers      = all_data['opory']
    piers_to_calc  = [pier for pier in all_piers if pier.calculate]
    piers_to_skip  = [pier for pier in all_piers if not pier.calculate]

    print(f'Опоры ({len(all_piers)} всего, {len(piers_to_calc)} к расчёту):')
    if piers_to_skip:
        print(f'  Пропущены (calculate=нет): '
              f'{[pier.pier_name for pier in piers_to_skip]}')
    for pier in piers_to_calc:
        transform_info = ''
        if pier.translate_x or pier.translate_y or pier.translate_z:
            transform_info += (f', перенос=({pier.translate_x:.2f}, '
                               f'{pier.translate_y:.2f}, {pier.translate_z:.2f})')
        if pier.rotate_angle_deg:
            transform_info += f', поворот={pier.rotate_angle_deg:.1f}°'
        def _pad_y_str(fr):
            if fr is None:
                return '—'
            asym = abs(fr.pad_y_right - fr.pad_y_left) > 1e-6
            y = (f'+Y={fr.pad_y_right:.3f}/−Y={fr.pad_y_left:.3f}'
                 if asym else f'±Y={fr.pad_y_right:.3f}')
            return f'x={fr.x_coordinate}, {y}'
        frame2_info = (f', рамка2({_pad_y_str(pier.frame2)})'
                       if pier.frame2 else '')
        piles_info = f', сваи={pier.pile_mct_file_path}' if pier.pile_mct_file_path else ''
        print(f'  {pier.pier_name} [{pier.geom_source}]: '
              f'ростверк={len(pier.footing_zones)} зон, '
              f'стойка={len(pier.column_zones)} зон, '
              f'ригель={len(pier.crossbeam_zones)} зон, '
              f'рамка1({_pad_y_str(pier.frame1)})'
              f'{frame2_info}{piles_info}{transform_info}')
    print()

    print(f'Грунт ({len(all_data["grunt"])}):')
    for soil in all_data['grunt']:
        active_influences = []
        if soil.liquefaction_present:
            active_influences.append('разжижение')
        if soil.lateral_pressure_y_present:
            active_influences.append('давление_Y')
        if soil.lateral_pressure_z_present:
            active_influences.append('давление_Z')
        if soil.water_mass_present:
            active_influences.append('масса воды')
        if soil.soil_load_on_footing:
            active_influences.append('нагрузка на ростверк')
        print(f'  {soil.pier_name}: '
              f'{", ".join(active_influences) or "нет грунтовых воздействий"}')
    print()

    validation_errors = validate_input_data(all_data)
    if validation_errors:
        print('Проверка данных:')
        for error_message in validation_errors:
            print(f'  {error_message}')
    else:
        print('Проверка данных: OK')

    print('\nМодуль 1 завершён.')

    # ── Модуль 2: генерация геометрии ────────────────────────────────────────
    print('\n' + '═' * 60)
    print('Модуль 2 — генерация параметрической геометрии')
    print('═' * 60)

    pier_results: dict[str, PierGeometryResult] = {}

    for pier in piers_to_calc:
        try:
            result = generate_pier_geometry(
                pier,
                bearing_rows = all_data['plety'],
                include_temp = False,   # no_temp — первый проход
            )
            pier_results[pier.pier_name] = result
        except ValueError as exc:
            print(f'  ОШИБКА [{pier.pier_name}]: {exc}')
            pier_results[pier.pier_name] = PierGeometryResult(
                pier_name=pier.pier_name, model=None)

    # ── Вывод результатов Модуля 2 ───────────────────────────────────────────
    for pier_name, result in pier_results.items():
        if result.mct_body_result is not None:
            print_mct_body_report(result)
        else:
            print_shaft_report(result)
            print_frames_report(result)   # включает координаты узлов рамок
        print_pile_report(result)
        if result.part4_result is not None and result.model is not None:
            print_part4_report(result.part4_result, result.model)

    successful = sum(1 for r in pier_results.values() if r.model is not None)
    failed     = len(pier_results) - successful
    print(f'\nМодуль 2 завершён: {successful} опор обработано'
          + (f', {failed} с ошибками' if failed else '') + '.')

    # ── Модуль 3, Часть 1: соответствие масс и нагрузок координатам ──────────
    print('\n' + '═' * 60)
    print('Модуль 3 (Часть 1) — координаты масс и нагрузок')
    print('═' * 60)

    load_assignments: dict[str, PierLoadAssignment] = build_all_load_assignments(
        piers           = piers_to_calc,
        all_masses_rows = all_data['masses'],
        all_plety_rows  = all_data['plety'],
        coord_indices   = {
            name: r.coord_index
            for name, r in pier_results.items()
            if r.coord_index
        },
    )

    print_module3_report(load_assignments)

    m3_ok   = sum(1 for a in load_assignments.values() if not a.warnings)
    m3_warn = sum(1 for a in load_assignments.values() if a.warnings)
    print(f'\nМодуль 3 (Часть 1) завершён: {m3_ok} опор без замечаний'
          + (f', {m3_warn} с предупреждениями' if m3_warn else '') + '.')

    # ── Модуль 3, Часть 2: массы от воды и разжиженного грунта ──────────────
    print('\n' + '═' * 60)
    print('Модуль 3 (Часть 2) — массы от воды и разжиженного грунта')
    print('═' * 60)

    fluid_mass_results: dict[str, FluidMassResult] = build_all_fluid_masses(
        piers=piers_to_calc,
        models={
            name: r.model
            for name, r in pier_results.items()
            if r.model is not None
        },
        soils=all_data['grunt'],
        gravity=project.gravity,
    )

    print_fluid_masses_report(fluid_mass_results)

    m3p2_ok = sum(1 for r in fluid_mass_results.values() if not r.warnings)
    m3p2_warn = sum(1 for r in fluid_mass_results.values() if r.warnings)
    print(f'\nМодуль 3 (Часть 2) завершён: {m3p2_ok} опор без замечаний'
          + (f', {m3p2_warn} с предупреждениями' if m3p2_warn else '') + '.')


if __name__ == '__main__':
    main()
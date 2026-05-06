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
from module_2 import generate_pier_geometry


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
        frame2_info = (f', рамка2(x={pier.frame2.x_coordinate})'
                       if pier.frame2 else '')
        piles_info = f', сваи={pier.pile_mct_file_path}' if pier.pile_mct_file_path else ''
        print(f'  {pier.pier_name} [{pier.geom_source}]: '
              f'ростверк={len(pier.footing_zones)} зон, '
              f'стойка={len(pier.column_zones)} зон, '
              f'ригель={len(pier.crossbeam_zones)} зон, '
              f'рамка1(x={pier.frame1.x_coordinate if pier.frame1 else "—"})'
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

    pier_models = {}  # pier_name → PierModel | None

    for pier in piers_to_calc:
        try:
            model = generate_pier_geometry(pier)
            pier_models[pier.pier_name] = model
        except ValueError as exc:
            print(f'  ОШИБКА [{pier.pier_name}]: {exc}')
            pier_models[pier.pier_name] = None

    successful = sum(1 for m in pier_models.values() if m is not None)
    failed     = len(pier_models) - successful
    print(f'\nМодуль 2 завершён: {successful} опор обработано'
          + (f', {failed} с ошибками' if failed else '') + '.')


if __name__ == '__main__':
    main()

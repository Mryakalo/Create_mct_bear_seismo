from pathlib import Path
from typing import Optional
import pandas as pd

from additional_functions import to_string, to_float, to_int, is_data_row, to_bool
from data_structures import ProjectParameters, BearingPlaneRow, MassesRow, SectionZone, FrameParameters, PierGeometry, \
    SoilInfluence


# ═══════════════════════════════════════════════════════════════════════════════
#  Модуль 1: Чтение входных данных
# ═══════════════════════════════════════════════════════════════════════════════

def read_excel_sheet(file_path: str, sheet_name: str,
                     key_row_number: int) -> pd.DataFrame:
    """
    Читает лист Excel и возвращает DataFrame.

    Структура листов с тройной шапкой:
      Строка key_row_number     — machine-readable ключи → имена колонок
      Строка key_row_number + 1 — описания для пользователя → пропускается
      Строки key_row_number + 2 и далее — данные

    key_row_number — 1-based номер строки с ключами.
    """
    dataframe = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        dtype=str,
        header=key_row_number - 1   # pandas использует 0-based индексацию
    )
    # Пропускаем строку с описаниями (первая строка после заголовка)
    dataframe = dataframe.iloc[1:].reset_index(drop=True)
    return dataframe


def read_project_parameters(file_path: str) -> ProjectParameters:
    """
    Читает лист «Проект».

    Структура: каждая строка — один параметр.
    Столбец A = метка (для пользователя)
    Столбец B = ключ (machine-readable)
    Столбец C = описание
    Столбец D = значение
    Строка 1 = заголовки колонок.
    """
    dataframe = pd.read_excel(file_path, sheet_name='Проект',
                              dtype=str, header=0)
    project = ProjectParameters()

    for _, row in dataframe.iterrows():
        parameter_key   = to_string(row.iloc[1])
        parameter_value = to_string(row.iloc[3])
        if parameter_key is None or parameter_value is None:
            continue
        if parameter_key == 'project_name':
            project.project_name = parameter_value
        elif parameter_key == 'gravity':
            project.gravity = to_float(parameter_value, 9.806)
        elif parameter_key == 'mu':
            project.friction_coefficient = to_float(parameter_value, 0.08)

    return project


def read_bearing_plane(file_path: str) -> list[BearingPlaneRow]:
    """
    Читает лист «Плеть».

    Строка 1 — суперзаголовки групп
    Строка 2 — подзаголовки групп
    Строка 3 — machine-readable ключи (header)
    Строка 4 — описания для пользователя (пропускается)
    Строка 5 и далее — данные (включая строки-разделители «Плеть N»)

    Каждой строке данных присваивается имя текущей плети.
    Строки-разделители и примечания фильтруются.
    """
    dataframe = read_excel_sheet(file_path, 'Плеть', key_row_number=3)

    result_rows: list[BearingPlaneRow] = []
    current_span_group = ''

    for _, excel_row in dataframe.iterrows():
        pier_name = to_string(excel_row.get('pier_name'))
        if pier_name is None:
            continue
        stripped = pier_name.lstrip()
        # Строка-разделитель плети
        if stripped.startswith('Плеть'):
            current_span_group = stripped
            continue
        # Строка-примечание
        if stripped.startswith('*'):
            continue

        row = BearingPlaneRow(
            pier_name             = pier_name,
            span_group_name       = current_span_group,
            z_hinge_elevation     = to_float(excel_row.get('z_hinge')),
            z_cg_elevation        = to_float(excel_row.get('z_cg')),
            z_road_elevation      = to_float(excel_row.get('z_road')),
            # Правая ОЧ
            right_bearing_number  = to_int(excel_row.get('r_bearing_no')),
            right_bearing_type_X  = to_string(excel_row.get('r_bearing_X'), 'fixed').lower(),
            right_bearing_type_Y  = to_string(excel_row.get('r_bearing_Y'), 'fixed').lower(),
            right_load_permanent  = to_float(excel_row.get('r_R_perm'), 0.0),
            right_load_temporary  = to_float(excel_row.get('r_R_temp'), 0.0),
            right_friction_X      = to_float(excel_row.get('r_mu_X'), 0.0),
            # Левая ОЧ
            left_bearing_number   = to_int(excel_row.get('l_bearing_no')),
            left_bearing_type_X   = to_string(excel_row.get('l_bearing_X'), 'fixed').lower(),
            left_bearing_type_Y   = to_string(excel_row.get('l_bearing_Y'), 'fixed').lower(),
            left_load_permanent   = to_float(excel_row.get('l_R_perm'), 0.0),
            left_load_temporary   = to_float(excel_row.get('l_R_temp'), 0.0),
            left_friction_X       = to_float(excel_row.get('l_mu_X'), 0.0),
        )
        result_rows.append(row)

    return result_rows


def read_masses_table(file_path: str) -> list[MassesRow]:
    """
    Читает лист «Массы».

    Строка 3 — ключи, строка 4 — описания.
    Одна опора может занимать несколько строк (граничная опора двух плетей).
    Python читает уже вычисленные Excel-формулами числа —
    перед запуском скрипта необходимо пересчитать формулы в Excel (F9).
    """
    dataframe = read_excel_sheet(file_path, 'Массы', key_row_number=3)
    result_rows: list[MassesRow] = []

    for _, excel_row in dataframe.iterrows():
        if not is_data_row(excel_row):
            continue

        row = MassesRow(
            pier_name              = to_string(excel_row.get('pier_name'), ''),
            gravity                = to_float(excel_row.get('g'), 9.806),
            span_group_row_start   = to_int(excel_row.get('plety_row_start')),
            span_group_row_end     = to_int(excel_row.get('plety_row_end')),
            # Правая ОЧ — постоянная
            right_bearing_number   = to_int(excel_row.get('r_bearing_no')),
            right_mass_X_permanent = to_float(excel_row.get('r_mx_mass'), 0.0),
            right_mass_X_z         = to_float(excel_row.get('r_mx_z')),
            right_mass_Y_permanent = to_float(excel_row.get('r_my_mass'), 0.0),
            right_mass_Y_z         = to_float(excel_row.get('r_my_z')),
            right_mass_Z_permanent = to_float(excel_row.get('r_mz_mass'), 0.0),
            right_mass_Z_z         = to_float(excel_row.get('r_mz_z')),
            # Правая ОЧ — временная
            right_mass_X_temporary = to_float(excel_row.get('r_mx_t_mass'), 0.0),
            right_mass_X_temp_z    = to_float(excel_row.get('r_mx_t_z')),
            right_mass_Y_temporary = to_float(excel_row.get('r_my_t_mass'), 0.0),
            right_mass_Y_temp_z    = to_float(excel_row.get('r_my_t_z')),
            right_mass_Z_temporary = to_float(excel_row.get('r_mz_t_mass'), 0.0),
            right_mass_Z_temp_z    = to_float(excel_row.get('r_mz_t_z')),
            # Левая ОЧ — постоянная
            left_bearing_number    = to_int(excel_row.get('l_bearing_no')),
            left_mass_X_permanent  = to_float(excel_row.get('l_mx_mass'), 0.0),
            left_mass_X_z          = to_float(excel_row.get('l_mx_z')),
            left_mass_Y_permanent  = to_float(excel_row.get('l_my_mass'), 0.0),
            left_mass_Y_z          = to_float(excel_row.get('l_my_z')),
            left_mass_Z_permanent  = to_float(excel_row.get('l_mz_mass'), 0.0),
            left_mass_Z_z          = to_float(excel_row.get('l_mz_z')),
            # Левая ОЧ — временная
            left_mass_X_temporary  = to_float(excel_row.get('l_mx_t_mass'), 0.0),
            left_mass_X_temp_z     = to_float(excel_row.get('l_mx_t_z')),
            left_mass_Y_temporary  = to_float(excel_row.get('l_my_t_mass'), 0.0),
            left_mass_Y_temp_z     = to_float(excel_row.get('l_my_t_z')),
            left_mass_Z_temporary  = to_float(excel_row.get('l_mz_t_mass'), 0.0),
            left_mass_Z_temp_z     = to_float(excel_row.get('l_mz_t_z')),
        )
        result_rows.append(row)

    return result_rows


def parse_section_zones(excel_row, part_prefix: str,
                        part_z_top: Optional[float], max_zones: int,
                        material_number: int) -> list[SectionZone]:
    """
    Читает зоны сечений для одной части опоры (ростверк/стойка/ригель).

    Ключи в Excel:
      {prefix}_sec_{k}           — номер сечения зоны k
      {prefix}_sec_{k}_ts_group  — включить в TS-GROUP (да/нет)
      {prefix}_sec_{k}_ts_no     — номер TS-GROUP
      {prefix}_sec_{k}_z_top     — верхняя граница зоны k по Z

    Последняя зона всегда заканчивается на part_z_top (верх части).
    Если part_z_top не задан (None), граница последней зоны остаётся
    из Excel — это будет поймано в validate_input_data.
    """
    zones: list[SectionZone] = []

    for zone_index in range(1, max_zones + 1):
        section_number = to_int(excel_row.get(f'{part_prefix}_sec_{zone_index}'))
        if section_number is None:
            break   # зоны нумеруются последовательно, пустая = конец

        zone_z_top   = to_float(excel_row.get(f'{part_prefix}_sec_{zone_index}_z_top'),
                                part_z_top)
        use_ts_group = to_bool(excel_row.get(f'{part_prefix}_sec_{zone_index}_ts_group',
                                             'нет'))
        ts_group_num = to_int(excel_row.get(f'{part_prefix}_sec_{zone_index}_ts_no'))

        zones.append(SectionZone(
            section_number  = section_number,
            material_number = material_number,
            zone_z_top      = zone_z_top if zone_z_top is not None else 0.0,
            use_ts_group    = use_ts_group,
            ts_group_number = ts_group_num,
        ))

    # Граница последней зоны всегда совпадает с верхом части
    if zones and part_z_top is not None:
        zones[-1].zone_z_top = part_z_top

    return zones


def parse_frame_parameters(excel_row, frame_number: int) -> Optional[FrameParameters]:
    """
    Читает параметры рамки из строки листа «Опоры».
    Возвращает None если рамка не задана (поле f{n}_x пустое).
    """
    prefix = f'f{frame_number}_'

    x_coordinate = to_float(excel_row.get(prefix + 'x'))
    if x_coordinate is None:
        return None   # рамка не задана

    return FrameParameters(
        frame_number                  = frame_number,
        x_coordinate                  = x_coordinate,
        pad_y_half_width              = to_float(excel_row.get(prefix + 'pad_y'), 0.0),
        pad_z_bottom                  = to_float(excel_row.get(prefix + 'pad_z_bot')),
        pad_z_top                     = to_float(excel_row.get(prefix + 'pad_z_top')),
        pad_section                   = to_int(excel_row.get(prefix + 'pad_sec')),
        pad_material                  = to_int(excel_row.get(prefix + 'pad_mat')),
        bearing_z_bottom              = to_float(excel_row.get(prefix + 'bear_z_bot')),
        bearing_section               = to_int(excel_row.get(prefix + 'bear_sec')),
        bearing_material              = to_int(excel_row.get(prefix + 'bear_mat')),
        frame_section                 = to_int(excel_row.get(prefix + 'frame_sec')),
        frame_material                = to_int(excel_row.get(prefix + 'frame_mat')),
        bearings_per_pad              = to_int(excel_row.get(prefix + 'num_bearings'), 1),
        shared_pad_with_other_frame   = to_bool(excel_row.get(prefix + 'shared_pad', 'нет')),
    )


def read_pier_geometry(file_path: str) -> list[PierGeometry]:
    """
    Читает лист «Опоры».

    Строка 1 — суперзаголовки групп
    Строка 2 — machine-readable ключи (header)
    Строка 3 — описания для пользователя (пропускается)
    Строка 4 и далее — данные

    Если geom_source = 'mct', поля геометрии (зоны сечений, рамки)
    не читаются и остаются пустыми — геометрия берётся из .mct файла.

    Аффинное преобразование (dx, dy, dz, angle) применяется ко всем
    узлам опоры в Модуле 2 (parametric) и Модуле 3 (mct).
    """
    dataframe = read_excel_sheet(file_path, 'Опоры', key_row_number=2)
    result_piers: list[PierGeometry] = []

    for _, excel_row in dataframe.iterrows():
        if not is_data_row(excel_row):
            continue

        geometry_source  = to_string(excel_row.get('geom_source'), 'parametric').lower()
        is_from_mct_file = (geometry_source == 'mct')

        footing_z_top   = to_float(excel_row.get('cap_z_top'))
        column_z_top    = to_float(excel_row.get('col_z_top'))
        crossbeam_z_top = to_float(excel_row.get('beam_z_top'))
        footing_material   = to_int(excel_row.get('cap_mat'), 1)
        column_material    = to_int(excel_row.get('col_mat'), 1)
        crossbeam_material = to_int(excel_row.get('beam_mat'), 1)

        pier = PierGeometry(
            pier_name             = to_string(excel_row.get('pier_name'), ''),
            geom_source           = geometry_source,
            calculate             = to_bool(excel_row.get('calculate', 'да')),
            span_group_row_start  = to_int(excel_row.get('plety_row_start')),
            span_group_row_end    = to_int(excel_row.get('plety_row_end')),
            mct_file_path         = to_string(excel_row.get('mct_path')),
            pile_mct_file_path    = to_string(excel_row.get('pile_mct_path')),
            # Аффинное преобразование
            translate_x           = to_float(excel_row.get('shift_x'),    0.0),
            translate_y           = to_float(excel_row.get('shift_y'),    0.0),
            translate_z           = to_float(excel_row.get('shift_z'),    0.0),
            rotate_angle_deg      = to_float(excel_row.get('rotation_angle'), 0.0),
            # Офсеты нумерации
            node_offset_footing   = to_int(excel_row.get('node_offset_cap'),    1),
            elem_offset_footing   = to_int(excel_row.get('elem_offset_cap'),    1),
            node_offset_column    = to_int(excel_row.get('node_offset_col'),    101),
            elem_offset_column    = to_int(excel_row.get('elem_offset_col'),    101),
            node_offset_crossbeam = to_int(excel_row.get('node_offset_beam'),   201),
            elem_offset_crossbeam = to_int(excel_row.get('elem_offset_beam'),   201),
            node_offset_frame1    = to_int(excel_row.get('node_offset_frame1'), 301),
            elem_offset_frame1    = to_int(excel_row.get('elem_offset_frame1'), 301),
            node_offset_frame2    = to_int(excel_row.get('node_offset_frame2'), 501),
            elem_offset_frame2    = to_int(excel_row.get('elem_offset_frame2'), 501),
            node_offset_piles     = to_int(excel_row.get('node_offset_piles'),  1001),
            elem_offset_piles     = to_int(excel_row.get('elem_offset_piles'),  1001),
            # Геометрия (только для parametric)
            footing_z_top      = footing_z_top if not is_from_mct_file else None,
            footing_mesh_step  = to_float(excel_row.get('cap_step'), 0.5),
            footing_zones      = parse_section_zones(
                excel_row, 'cap', footing_z_top, 2, footing_material
            ) if not is_from_mct_file else [],
            column_z_top       = column_z_top if not is_from_mct_file else None,
            column_mesh_step   = to_float(excel_row.get('col_step'), 0.5),
            column_zones       = parse_section_zones(
                excel_row, 'col', column_z_top, 3, column_material
            ) if not is_from_mct_file else [],
            crossbeam_z_top    = crossbeam_z_top if not is_from_mct_file else None,
            crossbeam_mesh_step = to_float(excel_row.get('beam_step'), 0.1),
            crossbeam_zones    = parse_section_zones(
                excel_row, 'beam', crossbeam_z_top, 4, crossbeam_material
            ) if not is_from_mct_file else [],
            frame1 = parse_frame_parameters(excel_row, 1) if not is_from_mct_file else None,
            frame2 = parse_frame_parameters(excel_row, 2) if not is_from_mct_file else None,
        )
        result_piers.append(pier)

    return result_piers


def read_soil_influences(file_path: str) -> list[SoilInfluence]:
    """
    Читает лист «Грунт».

    Строка 2 — ключи, строка 3 — описания.

    Боковое давление разделено на два независимых направления:
      y_pressure_* — давление по локальной оси Y элемента
      z_pressure_* — давление по локальной оси Z элемента
    Общие параметры грунта (pres_gamma, pres_phi) используются
    для обоих направлений.

    Ширина сечения для эпюры давления (cap_width, col_width, pile_width)
    постоянна по высоте и задаётся отдельно для каждой части опоры.
    """
    dataframe = read_excel_sheet(file_path, 'Грунт', key_row_number=2)
    result_soils: list[SoilInfluence] = []

    for _, excel_row in dataframe.iterrows():
        if not is_data_row(excel_row):
            continue

        soil = SoilInfluence(
            pier_name                  = to_string(excel_row.get('pier_name'), ''),
            # Площади сечений
            footing_area_top           = to_float(excel_row.get('cap_area_top')),
            footing_area_bottom        = to_float(excel_row.get('cap_area_bot')),
            column_area_top            = to_float(excel_row.get('col_area_top')),
            column_area_bottom         = to_float(excel_row.get('col_area_bot')),
            pile_area_top              = to_float(excel_row.get('pile_area_top')),
            pile_area_bottom           = to_float(excel_row.get('pile_area_bot')),
            # Ширина сечений
            footing_width              = to_float(excel_row.get('cap_width')),
            column_width               = to_float(excel_row.get('col_width')),
            pile_width                 = to_float(excel_row.get('pile_width')),
            # Разжижение
            liquefaction_present       = to_bool(excel_row.get('liq_present', 'нет')),
            liquefaction_z_top         = to_float(excel_row.get('liq_z_top')),
            liquefaction_z_bottom      = to_float(excel_row.get('liq_z_bot')),
            liquefaction_unit_weight   = to_float(excel_row.get('liq_gamma')),
            # Давление — ось Y
            lateral_pressure_y_present = to_bool(excel_row.get('y_pressure_present', 'нет')),
            pressure_y_z_surface       = to_float(excel_row.get('y_pres_z_surf')),
            pressure_y_z_bottom        = to_float(excel_row.get('y_pres_z_bot')),
            # Давление — ось Z
            lateral_pressure_z_present = to_bool(excel_row.get('z_pressure_present', 'нет')),
            pressure_z_z_surface       = to_float(excel_row.get('z_pres_z_surf')),
            pressure_z_z_bottom        = to_float(excel_row.get('z_pres_z_bot')),
            # Общие параметры грунта
            pressure_unit_weight       = to_float(excel_row.get('pres_gamma')),
            pressure_friction_angle    = to_float(excel_row.get('pres_phi')),
            # Масса воды
            water_mass_present         = to_bool(excel_row.get('water_present', 'нет')),
            water_z_top                = to_float(excel_row.get('water_z_top')),
            water_z_bottom             = to_float(excel_row.get('water_z_bot')),
            # Нагрузка на ростверк
            soil_load_on_footing       = to_bool(excel_row.get('soil_on_cap_present', 'нет')),
            soil_load_unit_weight      = to_float(excel_row.get('soil_on_cap_gamma')),
            soil_load_height           = to_float(excel_row.get('soil_on_cap_h')),
        )
        result_soils.append(soil)

    return result_soils


def read_all_input_data(file_path: str) -> dict:
    """
    Читает все листы Excel и возвращает структурированные данные:
    {
        'project': ProjectParameters,
        'plety':   [BearingPlaneRow, ...],
        'masses':  [MassesRow, ...],
        'opory':   [PierGeometry, ...],
        'grunt':   [SoilInfluence, ...],
    }
    """
    return {
        'project': read_project_parameters(file_path),
        'plety':   read_bearing_plane(file_path),
        'masses':  read_masses_table(file_path),
        'opory':   read_pier_geometry(file_path),
        'grunt':   read_soil_influences(file_path),
    }


def validate_input_data(all_data: dict) -> list[str]:
    """
    Проверяет полноту и корректность прочитанных данных.
    Возвращает список строк с предупреждениями и ошибками.
    """
    error_messages = []

    piers_by_name  = {pier.pier_name: pier for pier in all_data['opory']}
    masses_by_pier = {}
    for mass_row in all_data['masses']:
        masses_by_pier.setdefault(mass_row.pier_name, []).append(mass_row)
    soil_by_pier   = {soil.pier_name: soil for soil in all_data['grunt']}

    for pier_name, pier in piers_by_name.items():

        # ── Наличие связанных данных ────────────────────────────────────────
        if pier_name not in masses_by_pier:
            error_messages.append(
                f'ОШИБКА [{pier_name}]: нет строк в листе "Массы"')
        if pier_name not in soil_by_pier:
            error_messages.append(
                f'ПРЕДУПРЕЖДЕНИЕ [{pier_name}]: нет строки в листе "Грунт"')

        # ── Геометрия ───────────────────────────────────────────────────────
        if pier.geom_source == 'parametric':
            if pier.footing_z_top is None:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: не задан cap_z_top (верх ростверка)')
            if pier.column_z_top is None:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: не задан col_z_top (верх стойки)')
            if pier.crossbeam_z_top is None:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: не задан beam_z_top (верх ригеля)')
            if not pier.footing_zones:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: ростверк — не задано ни одного сечения')
            if not pier.column_zones:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: стойка — не задано ни одного сечения')
            if not pier.crossbeam_zones:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: ригель — не задано ни одного сечения')
            if pier.frame1 is None:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: рамка 1 не задана')

        elif pier.geom_source == 'mct':
            if not pier.mct_file_path:
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: geom_source=mct, но путь к файлу не задан')
            elif not Path(pier.mct_file_path).exists():
                error_messages.append(
                    f'ОШИБКА [{pier_name}]: файл геометрии не найден: {pier.mct_file_path}')

        if pier.pile_mct_file_path and not Path(pier.pile_mct_file_path).exists():
            error_messages.append(
                f'ОШИБКА [{pier_name}]: файл свай не найден: {pier.pile_mct_file_path}')

        # ── Перекрытие офсетов нумерации узлов ─────────────────────────────
        node_offsets = {
            'ростверк':  pier.node_offset_footing,
            'стойка':    pier.node_offset_column,
            'ригель':    pier.node_offset_crossbeam,
            'рамка 1':   pier.node_offset_frame1,
            'рамка 2':   pier.node_offset_frame2,
            'сваи':      pier.node_offset_piles,
        }
        seen_node_offsets: dict[int, str] = {}
        for part_name, offset_value in node_offsets.items():
            if offset_value in seen_node_offsets:
                error_messages.append(
                    f'ПРЕДУПРЕЖДЕНИЕ [{pier_name}]: офсет узлов "{part_name}" '
                    f'совпадает с "{seen_node_offsets[offset_value]}" ({offset_value})')
            seen_node_offsets[offset_value] = part_name

        # ── Перекрытие офсетов нумерации элементов ─────────────────────────
        elem_offsets = {
            'ростверк':  pier.elem_offset_footing,
            'стойка':    pier.elem_offset_column,
            'ригель':    pier.elem_offset_crossbeam,
            'рамка 1':   pier.elem_offset_frame1,
            'рамка 2':   pier.elem_offset_frame2,
            'сваи':      pier.elem_offset_piles,
        }
        seen_elem_offsets: dict[int, str] = {}
        for part_name, offset_value in elem_offsets.items():
            if offset_value in seen_elem_offsets:
                error_messages.append(
                    f'ПРЕДУПРЕЖДЕНИЕ [{pier_name}]: офсет элементов "{part_name}" '
                    f'совпадает с "{seen_elem_offsets[offset_value]}" ({offset_value})')
            seen_elem_offsets[offset_value] = part_name

        # ── Грунтовые воздействия ───────────────────────────────────────────
        if pier_name in soil_by_pier:
            soil = soil_by_pier[pier_name]

            # Разжижение
            if soil.liquefaction_present:
                if soil.liquefaction_z_top is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: разжижение — не задан liq_z_top')
                if soil.liquefaction_z_bottom is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: разжижение — не задан liq_z_bot')
                if soil.liquefaction_unit_weight is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: разжижение — не задан liq_gamma')

            # Боковое давление — оба направления
            for axis, present, z_surf, z_bot in [
                ('Y', soil.lateral_pressure_y_present,
                       soil.pressure_y_z_surface, soil.pressure_y_z_bottom),
                ('Z', soil.lateral_pressure_z_present,
                       soil.pressure_z_z_surface, soil.pressure_z_z_bottom),
            ]:
                if present:
                    if z_surf is None:
                        error_messages.append(
                            f'ОШИБКА [{pier_name}]: давление по оси {axis} — '
                            f'не задана Z поверхности грунта')
                    if z_bot is None:
                        error_messages.append(
                            f'ОШИБКА [{pier_name}]: давление по оси {axis} — '
                            f'не задан Z низа эпюры')
                    if soil.pressure_unit_weight is None:
                        error_messages.append(
                            f'ОШИБКА [{pier_name}]: давление по оси {axis} — '
                            f'не задан pres_gamma')
                    if soil.pressure_friction_angle is None:
                        error_messages.append(
                            f'ОШИБКА [{pier_name}]: давление по оси {axis} — '
                            f'не задан pres_phi')

            # Масса воды
            if soil.water_mass_present:
                if soil.water_z_top is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: масса воды — не задан water_z_top')
                if soil.water_z_bottom is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: масса воды — не задан water_z_bot')

            # Нагрузка на ростверк
            if soil.soil_load_on_footing:
                if soil.soil_load_unit_weight is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: нагрузка на ростверк — '
                        f'не задан soil_on_cap_gamma')
                if soil.soil_load_height is None:
                    error_messages.append(
                        f'ОШИБКА [{pier_name}]: нагрузка на ростверк — '
                        f'не задан soil_on_cap_h')

    return error_messages

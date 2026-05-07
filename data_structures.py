from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных для модуля 1
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProjectParameters:
    """
    Параметры проекта из листа «Проект».
    Строка 2 = ключ (machine-readable), столбец D = значение.
    """
    project_name:         str   = ''
    gravity:              float = 9.806  # м/с² — переопределяется из листа «Проект»
    friction_coefficient: float = 0.08   # μ — коэффициент трения опорных частей


@dataclass
class BearingPlaneRow:
    """
    Одна строка листа «Плеть» — одна опора в одной плети.

    z_hinge, z_cg, z_road — общие для правой (r_) и левой (l_) опорных частей.
    Одна опора может присутствовать в нескольких строках,
    если она является граничной и принадлежит двум плетям.
    """
    pier_name:              str            = ''
    span_group_name:        str            = ''   # «Плеть 1», «Плеть 2», ...

    z_hinge_elevation:      Optional[float] = None  # отметка шарнира ОЧ
    z_cg_elevation:         Optional[float] = None  # отметка ЦТ пролёта
    z_road_elevation:       Optional[float] = None  # отметка верха проезжей части

    # Правая опорная часть (СПРАВА по ходу возрастания пикетажа)
    right_bearing_number:   Optional[int]  = None
    right_bearing_type_X:   str            = 'fixed'   # fixed / movable
    right_bearing_type_Y:   str            = 'fixed'
    right_load_permanent:   float          = 0.0        # R_perm, тс
    right_load_temporary:   float          = 0.0        # R_temp, тс
    right_friction_X:       float          = 0.0        # μX

    # Левая опорная часть (СЛЕВА по ходу возрастания пикетажа)
    left_bearing_number:    Optional[int]  = None
    left_bearing_type_X:    str            = 'fixed'
    left_bearing_type_Y:    str            = 'fixed'
    left_load_permanent:    float          = 0.0
    left_load_temporary:    float          = 0.0
    left_friction_X:        float          = 0.0


@dataclass
class MassesRow:
    """
    Одна строка листа «Массы» — вычисленные массы для одной опоры.

    Одна опора может занимать несколько строк, если она является
    граничной между двумя плетями (тогда для каждой рамки своя строка).

    Python читает уже вычисленные Excel-формулами числа.
    Перед запуском скрипта необходимо пересчитать формулы в Excel.
    """
    pier_name:               str            = ''
    gravity:                 float          = 9.806  # м/с² — переопределяется из листа «Проект»
    span_group_row_start:    Optional[int]  = None  # строка начала плети в листе «Плеть»
    span_group_row_end:      Optional[int]  = None  # строка конца плети в листе «Плеть»

    # Правая ОЧ — постоянная нагрузка
    right_bearing_number:    Optional[int]  = None
    right_mass_X_permanent:  float          = 0.0   # mX, тс·с²/м
    right_mass_X_z:          Optional[float] = None  # узел Z для mX (z_hinge)
    right_mass_Y_permanent:  float          = 0.0   # mY
    right_mass_Y_z:          Optional[float] = None  # узел Z для mY (z_cg)
    right_mass_Z_permanent:  float          = 0.0   # mZ
    right_mass_Z_z:          Optional[float] = None  # узел Z для mZ (z_cg)

    # Правая ОЧ — временная нагрузка
    right_mass_X_temporary:  float          = 0.0
    right_mass_X_temp_z:     Optional[float] = None
    right_mass_Y_temporary:  float          = 0.0
    right_mass_Y_temp_z:     Optional[float] = None
    right_mass_Z_temporary:  float          = 0.0
    right_mass_Z_temp_z:     Optional[float] = None

    # Левая ОЧ — постоянная нагрузка
    left_bearing_number:     Optional[int]  = None
    left_mass_X_permanent:   float          = 0.0
    left_mass_X_z:           Optional[float] = None
    left_mass_Y_permanent:   float          = 0.0
    left_mass_Y_z:           Optional[float] = None
    left_mass_Z_permanent:   float          = 0.0
    left_mass_Z_z:           Optional[float] = None

    # Левая ОЧ — временная нагрузка
    left_mass_X_temporary:   float          = 0.0
    left_mass_X_temp_z:      Optional[float] = None
    left_mass_Y_temporary:   float          = 0.0
    left_mass_Y_temp_z:      Optional[float] = None
    left_mass_Z_temporary:   float          = 0.0
    left_mass_Z_temp_z:      Optional[float] = None


@dataclass
class SectionZone:
    """
    Зона сечения для ростверка, стойки или ригеля.
    Каждая часть разбивается на зоны по высоте Z,
    в каждой зоне своё сечение и (опционально) TS-GROUP.
    """
    section_number:  int
    material_number: int
    zone_z_top:      float          # верхняя граница зоны по Z, м
    use_ts_group:    bool = False    # включить в *TS-GROUP
    ts_group_number: Optional[int] = None


@dataclass
class FrameParameters:
    """
    Параметры одной рамки опоры (рамка 1 или рамка 2).

    Структура рамки снизу вверх:
      подферменник → опорная часть → вертикаль рамки → горизонталь рамки
    """
    frame_number:       int   = 1
    x_coordinate:       float = 0.0   # X-координата рамки вдоль пролёта, м
    pad_y_half_width:   float = 0.0   # Y подферменника симметр. (одна сторона), м
    pad_y_right:        float = 0.0   # Y правого подферменника (+Y сторона), м
    pad_y_left:         float = 0.0   # Y левого  подферменника (−Y сторона, >0), м

    pad_z_bottom:       Optional[float] = None  # Z низа подферменника (= верх ригеля)
    pad_z_top:          Optional[float] = None  # Z верха подферменника
    pad_section:        Optional[int]   = None
    pad_material:       Optional[int]   = None

    bearing_z_bottom:   Optional[float] = None  # Z низа опорной части
    bearing_section:    Optional[int]   = None
    bearing_material:   Optional[int]   = None  # материал no-sw (без собств. веса)

    frame_section:      Optional[int]   = None  # сечение всех элементов рамки
    frame_material:     Optional[int]   = None

    bearings_per_pad:   int  = 1     # 1 или 2 ОЧ на один подферменник
    shared_pad_with_other_frame: bool = False  # общий подф. с соседней рамкой


@dataclass
class PierGeometry:
    """
    Геометрические параметры опоры из листа «Опоры».

    geom_source = 'parametric': скрипт генерирует узлы и элементы по параметрам.
    geom_source = 'mct':        геометрия берётся из готового .mct файла;
                                 поля cap_zones, col_zones, beam_zones,
                                 frame1, frame2 при этом не используются.

    Аффинное преобразование применяется ко всем узлам опоры (включая сваи):
      1. Поворот вокруг глобальной оси Z на rotate_angle_deg (CCW при взгляде сверху).
      2. Перенос на (translate_x, translate_y, translate_z).
    Бета-угол всех вертикальных элементов устанавливается равным rotate_angle_deg.
    """
    pier_name:              str  = ''
    geom_source:            str  = 'parametric'  # 'parametric' или 'mct'
    calculate:              bool = True           # включить в расчёт

    span_group_row_start:   Optional[int] = None
    span_group_row_end:     Optional[int] = None

    mct_file_path:          Optional[str] = None  # путь к .mct тела опоры
    pile_mct_file_path:     Optional[str] = None  # путь к .mct свай

    # Аффинное преобразование (поворот → перенос)
    translate_x:            float = 0.0  # dx, м
    translate_y:            float = 0.0  # dy, м
    translate_z:            float = 0.0  # dz, м
    rotate_angle_deg:       float = 0.0  # angle, ° (CCW при взгляде сверху)

    # Офсеты нумерации узлов и элементов
    node_offset_footing:    int = 1      # ростверк
    elem_offset_footing:    int = 1
    node_offset_column:     int = 101    # стойка
    elem_offset_column:     int = 101
    node_offset_crossbeam:  int = 201    # ригель
    elem_offset_crossbeam:  int = 201
    node_offset_frame1:     int = 301    # рамка 1
    elem_offset_frame1:     int = 301
    node_offset_frame2:     int = 501    # рамка 2
    elem_offset_frame2:     int = 501
    node_offset_piles:      int = 1001   # сваи
    elem_offset_piles:      int = 1001

    # Ростверк (до 2 зон сечений по Z)
    footing_z_top:          Optional[float] = None
    footing_mesh_step:      float = 0.5
    footing_zones:          list = field(default_factory=list)  # [SectionZone]

    # Стойка (до 3 зон сечений по Z)
    column_z_top:           Optional[float] = None
    column_mesh_step:       float = 0.5
    column_zones:           list = field(default_factory=list)

    # Ригель (до 4 зон сечений по Z)
    crossbeam_z_top:        Optional[float] = None
    crossbeam_mesh_step:    float = 0.1
    crossbeam_zones:        list = field(default_factory=list)

    # Рамки
    frame1:                 Optional[FrameParameters] = None
    frame2:                 Optional[FrameParameters] = None


@dataclass
class SoilInfluence:
    """
    Грунтовые воздействия на опору из листа «Грунт».

    Боковое давление разделено на два независимых направления:
      - по локальной оси Y элемента (y_pressure_*)
      - по локальной оси Z элемента (z_pressure_*)
    Оба направления используют общие γ и φ, но могут иметь
    разные зоны по высоте (z_surface, z_bottom).

    Площади сечений (для масс воды и разжижения) задаются зонами по высоте:
      - ростверк: 2 зоны (sec1 / sec2)
      - стойка:   3 зоны (sec1 / sec2 / sec3)
      - свая:     1 зона

    Ширины сечений (для бокового давления) также задаются зонами:
      - ростверк: 2 зоны (sec1 / sec2)
      - стойка:   3 зоны (sec1 / sec2 / sec3)
      - свая:     1 зона
    """
    pier_name:                   str = ''

    # Площади сечений ростверка (для масс воды и разжижения)
    footing_area_sec1_top:       Optional[float] = None   # S ростверка зона 1 верх, м²
    footing_area_sec1_bottom:    Optional[float] = None   # S ростверка зона 1 низ, м²
    footing_area_sec2_top:       Optional[float] = None   # S ростверка зона 2 верх, м²
    footing_area_sec2_bottom:    Optional[float] = None   # S ростверка зона 2 низ, м²

    # Площади сечений стойки
    column_area_sec1_top:        Optional[float] = None   # S стойки зона 1 верх, м²
    column_area_sec1_bottom:     Optional[float] = None   # S стойки зона 1 низ, м²
    column_area_sec2_top:        Optional[float] = None   # S стойки зона 2 верх, м²
    column_area_sec2_bottom:     Optional[float] = None   # S стойки зона 2 низ, м²
    column_area_sec3_top:        Optional[float] = None   # S стойки зона 3 верх, м²
    column_area_sec3_bottom:     Optional[float] = None   # S стойки зона 3 низ, м²

    # Площади сечений сваи
    pile_area_top:               Optional[float] = None   # S сваи вверху, м²
    pile_area_bottom:            Optional[float] = None   # S сваи внизу, м²

    # Ширины сечений ростверка (для бокового давления грунта)
    footing_width_sec1:          Optional[float] = None   # ширина ростверка зона 1, м
    footing_width_sec2:          Optional[float] = None   # ширина ростверка зона 2, м

    # Ширины сечений стойки
    column_width_sec1:           Optional[float] = None   # ширина стойки зона 1, м
    column_width_sec2:           Optional[float] = None   # ширина стойки зона 2, м
    column_width_sec3:           Optional[float] = None   # ширина стойки зона 3, м

    # Ширина сечения сваи
    pile_width:                  Optional[float] = None   # pile_width, м

    # Разжиженный грунт
    liquefaction_present:        bool = False
    liquefaction_z_top:          Optional[float] = None
    liquefaction_z_bottom:       Optional[float] = None
    liquefaction_unit_weight:    Optional[float] = None   # γ, тс/м³

    # Боковое давление — по локальной оси Y элемента
    lateral_pressure_y_present:  bool = False
    pressure_y_z_surface:        Optional[float] = None   # Z поверхности грунта
    pressure_y_z_bottom:         Optional[float] = None   # Z низа эпюры давления

    # Боковое давление — по локальной оси Z элемента
    lateral_pressure_z_present:  bool = False
    pressure_z_z_surface:        Optional[float] = None
    pressure_z_z_bottom:         Optional[float] = None

    # Общие параметры грунта для обоих направлений давления
    pressure_unit_weight:        Optional[float] = None   # γ, тс/м³
    pressure_friction_angle:     Optional[float] = None   # φ, градусы

    # Масса воды
    water_mass_present:          bool = False
    water_z_top:                 Optional[float] = None
    water_z_bottom:              Optional[float] = None

    # Нагрузка от грунта на ростверк
    soil_load_on_footing:        bool = False
    soil_load_unit_weight:       Optional[float] = None   # γ, тс/м³
    soil_load_height:            Optional[float] = None   # h — высота грунта над ростверком, м

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных для модуля 2
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Node:
    """Узел конечно-элементной модели."""
    node_id: int
    x: float
    y: float
    z: float


@dataclass
class Element:
    """Стержневой элемент КЭ-модели."""
    elem_id:         int
    node_i:          int          # id начального узла
    node_j:          int          # id конечного узла
    section_number:  int
    material_number: int


@dataclass
class TsGroup:
    """Группа элементов для директивы *TS-GROUP в Midas Civil."""
    group_number: int
    elem_ids:     list[int] = field(default_factory=list)


@dataclass
class FrameRLS:
    """
    Условие опирания (Release) для элемента опорной части рамки.

    Задаёт шарниры на концах элемента «опорная часть».
    В Midas Civil директива *FRAME-RLS описывает разрыв жёсткостей
    на концах стержня (node_i = низ, node_j = верх).

    Всегда освобождаются My и Mz (шарниры по обоим изгибным моментам).
    Дополнительно, в зависимости от типа ОЧ:
      - movable_X → освобождается Fx (скольжение вдоль X)
      - movable_Y → освобождается Fy (скольжение вдоль Y)

    release_i / release_j — кортежи из 6 bool:
        (Fx, Fy, Fz, Mx, My, Mz)  для конца i (низ) и j (верх).
    По умолчанию шарниры ставятся на верхний конец (j) элемента ОЧ,
    т.е. в точке z_hinge.
    """
    elem_id:    int
    release_i:  tuple[bool, bool, bool, bool, bool, bool] = (
        False, False, False, False, False, False)
    release_j:  tuple[bool, bool, bool, bool, bool, bool] = (
        False, False, False, False, True,  True)   # My, Mz на верхнем конце


@dataclass
class SpringSupport:
    """
    Упругая опора (*SPRING в Midas Civil).

    Привязана к узлу node_id.
    spring_type  — тип пружины ('LINEAR', 'NONLINEAR', ...).
    sdx, sdy     — жёсткости по X и Y (тс/м).
    sdz          — жёсткость по Z.
    srx, sry, srz — жёсткости вращения.
    group_id     — номер группы (если задан).
    raw_tail     — остаток строки после sdz до конца (хранится «как есть»
                   для точного воспроизведения формата Midas Civil).
    """
    node_id:    int
    spring_type: str
    sdx:        float
    sdy:        float
    raw_tail:   str   # всё после sdy — хранится дословно для вывода в .mct


@dataclass
class PierModel:
    """
    Полная КЭ-модель одной опоры.
    Часть 1 заполняет nodes, elements, ts_groups.
    Часть 2 добавляет рамки (frame_rls).
    Часть 3 добавляет сваи (nodes, elements) и пружины (springs).
    """
    pier_name:  str
    nodes:      dict[int, Node]          = field(default_factory=dict)  # node_id → Node
    elements:   dict[int, Element]       = field(default_factory=dict)  # elem_id → Element
    ts_groups:  dict[int, TsGroup]       = field(default_factory=dict)  # group_number → TsGroup
    frame_rls:  dict[int, FrameRLS]      = field(default_factory=dict)  # elem_id → FrameRLS
    springs:    dict[int, SpringSupport] = field(default_factory=dict)  # node_id → SpringSupport

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных модуль 2, часть 3
# ═══════════════════════════════════════════════════════════════════════════════
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
#  Структуры данных модуль 2, часть 4
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RigidLink:
    """
    Жёсткая связь (*RIGID-LINK в Midas Civil).

    master_node_id  — мастер-узел (ведущий).
    slave_node_ids  — список слейв-узлов.
    dof_flags       — кортеж из 6 bool (Dx,Dy,Dz,Rx,Ry,Rz): True = связана степень свободы.
                      По умолчанию все 6 СС связаны.
    """
    link_id:        int
    master_node_id: int
    slave_node_ids: list[int] = field(default_factory=list)
    dof_flags:      tuple[bool, bool, bool, bool, bool, bool] = (
        True, True, True, True, True, True)

    # Человекочитаемое описание (не влияет на вывод в .mct)
    description: str = ''


@dataclass
class Constraint:
    """
    Граничное условие (*CONSTRAINT в Midas Civil).

    node_id  — узел.
    flags    — кортеж из 7 значений: (Dx, Dy, Dz, Rx, Ry, Rz, тип).
               1 = закреплено, 0 = свободно.
               Последний элемент — тип опоры (0 = обычная, 1 = пружинная и т.п.).
               По умолчанию: полное защемление без указания типа.
    """
    node_id: int
    flags:   tuple[int, int, int, int, int, int, int] = (1, 1, 1, 1, 1, 1, 0)

    description: str = ''


# Стандартные маски ГУ
CONSTRAINT_FULL   = (1, 1, 1, 1, 1, 1, 0)   # полное защемление
CONSTRAINT_DZ_RZ  = (0, 0, 1, 0, 0, 1, 0)   # только Dz + Rz (низ свай)

# ═══════════════════════════════════════════════════════════════════════════════
#  Структура данных модуля 2, часть 5
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Part5Result:
    """
    Результат аффинного преобразования (для main и Модуля 5).

    Attributes
    ----------
    applied : bool
        True если преобразование действительно выполнялось
        (False при fast-path нулевого преобразования).
    rotate_angle_deg : float
        Угол поворота CCW, градусы.
    translate : tuple[float, float, float]
        Вектор переноса (dx, dy, dz), м.
    n_nodes_transformed : int
        Количество узлов, у которых пересчитаны координаты.
    n_elems_beta_set : int
        Количество вертикальных элементов, которым присвоен бета-угол.
    errors : list[str]
        Ошибки, не прерывающие расчёт (для логирования в main).
    """
    applied:              bool  = False
    rotate_angle_deg:     float = 0.0
    translate:            tuple = (0.0, 0.0, 0.0)
    n_nodes_transformed:  int   = 0
    n_elems_beta_set:     int   = 0
    errors:               list  = field(default_factory=list)
# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных Модуля 3
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConcentratedLoad:
    """
    Сосредоточенная нагрузка в узле (нагрузки от пролётных строений).

    direction: 'FX' | 'FY' | 'FZ'
    value    : тс (знак: отрицательный = вниз/против оси)
    """
    node_id:   int
    direction: str
    value:     float


@dataclass
class NodalMass:
    """
    Сосредоточенная масса в узле (*MASS в Midas Civil).

    mx, my, mz — тс·с²/м
    """
    node_id: int
    mx:      float = 0.0
    my:      float = 0.0
    mz:      float = 0.0


@dataclass
class TrapezoidalLoad:
    """
    Трапециевидная нагрузка на элемент (боковое давление грунта).

    direction: 'GX' | 'GY' | 'GZ' (глобальные оси)
    value_i / value_j — тс/м в узлах i и j элемента
    """
    elem_id:   int
    direction: str
    value_i:   float
    value_j:   float


@dataclass
class Part3Result:
    """
    Полный результат Модуля 3 — нагрузки и массы для одной опоры.

    Схема 1 (только постоянные):
        permanent_loads   — вертикальные силы от постоянных нагрузок ОЧ
        permanent_masses  — массы от постоянных нагрузок ОЧ

    Схема 2 (постоянные + временные):
        temporary_loads   — вертикальные силы (постоянные + временные)
        temporary_masses  — массы (постоянные + временные)

    Общие для обеих схем:
        water_masses          — горизонтальные массы от воды
        liquefaction_masses   — горизонтальные массы от разжиженного грунта
        lateral_loads_y       — боковое давление грунта по Y
        lateral_loads_z       — боковое давление грунта по Z
        soil_vertical_load    — вертикальная сила от грунта на ростверк
        soil_vertical_mass    — масса по Z от грунта на ростверк
    """
    permanent_loads:       list['ConcentratedLoad']  = field(default_factory=list)
    permanent_masses:      list['NodalMass']          = field(default_factory=list)

    temporary_loads:       list['ConcentratedLoad']  = field(default_factory=list)
    temporary_masses:      list['NodalMass']          = field(default_factory=list)

    water_masses:          list['NodalMass']          = field(default_factory=list)
    liquefaction_masses:   list['NodalMass']          = field(default_factory=list)

    lateral_loads_y:       list['TrapezoidalLoad']   = field(default_factory=list)
    lateral_loads_z:       list['TrapezoidalLoad']   = field(default_factory=list)

    soil_vertical_load:    Optional['ConcentratedLoad'] = None
    soil_vertical_mass:    Optional['NodalMass']         = None

    warnings: list[str] = field(default_factory=list)
    errors:   list[str] = field(default_factory=list)


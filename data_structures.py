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

    Площади сечений задаются посекционно (до 2 зон для ростверка,
    до 3 зон для стойки) — соответствует структуре листа «Грунт».
    Ширина сечения для эпюры давления также задаётся по зонам.
    """
    pier_name:                   str = ''

    # Площади сечений ростверка (до 2 зон, для масс воды и разжижения)
    footing_area_sec1_top:       Optional[float] = None   # S ростверка зона 1 вверху, м²
    footing_area_sec1_bottom:    Optional[float] = None   # S ростверка зона 1 внизу, м²
    footing_area_sec2_top:       Optional[float] = None   # S ростверка зона 2 вверху, м²
    footing_area_sec2_bottom:    Optional[float] = None   # S ростверка зона 2 внизу, м²

    # Площади сечений стойки (до 3 зон)
    column_area_sec1_top:        Optional[float] = None   # S стойки зона 1 вверху, м²
    column_area_sec1_bottom:     Optional[float] = None   # S стойки зона 1 внизу, м²
    column_area_sec2_top:        Optional[float] = None   # S стойки зона 2 вверху, м²
    column_area_sec2_bottom:     Optional[float] = None   # S стойки зона 2 внизу, м²
    column_area_sec3_top:        Optional[float] = None   # S стойки зона 3 вверху, м²
    column_area_sec3_bottom:     Optional[float] = None   # S стойки зона 3 внизу, м²

    # Площади сечений сваи
    pile_area_top:               Optional[float] = None   # S сваи вверху, м²
    pile_area_bottom:            Optional[float] = None   # S сваи внизу, м²

    # Ширина сечений ростверка по зонам (для бокового давления грунта)
    footing_sec1_width:          Optional[float] = None   # cap_sec_1_width, м
    footing_sec2_width:          Optional[float] = None   # cap_sec_2_width, м

    # Ширина сечений стойки по зонам
    column_sec1_width:           Optional[float] = None   # col_sec_1_width, м
    column_sec2_width:           Optional[float] = None   # col_sec_2_width, м
    column_sec3_width:           Optional[float] = None   # col_sec_3_width, м

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
class ShaftPartResult:
    """Итог мешинга одной части стержня (для вывода в main)."""
    name: str
    z_bottom: float
    z_top: float
    n_nodes: int
    n_elems: int
    elem_offset: int


@dataclass
class BearingMeta:
    """Метаданные одной опорной части (для вывода в main)."""
    side: str  # 'правая (+Y)' / 'левая (−Y)'
    bn: Optional[int]
    x: float
    y: float
    z_bot: float  # z верха подферменника
    z_top: float  # z_hinge
    height: float
    type_x: str  # fixed / movable
    type_y: str


@dataclass
class FrameResult:
    """Итог построения одной рамки (для вывода в main)."""
    frame_number: int
    x_coordinate: float
    pad_z_bottom: float
    pad_z_top: float
    pad_y_half_width: float  # оставлено для обратной совместимости (среднее или симм. значение)
    pad_y_right: float  # Y правого подферменника (+Y сторона)
    pad_y_left: float  # Y левого подферменника  (−Y сторона, хранится как положительное)
    pad_section: int
    pad_material: int
    bearing_section: int
    bearing_material: int
    frame_section: int
    frame_material: int
    z_hinge: float
    z_cg: float
    z_road: float
    include_temp: bool
    n_nodes: int
    n_elems: int
    bearing_metas: list[BearingMeta]
    elem_labels: list[tuple[int, str]]  # [(elem_id, sublabel), ...]



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
#  Структуры данных Модуля 3, Часть 1
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LoadPoint:
    """
    Одна точка приложения нагрузки/массы на опору.

    Координаты x, y общие для всех нагрузок и масс данной ОЧ.
    Каждая нагрузка и каждая масса прикладывается на своей z-отметке:

      Вертикальные нагрузки:
        z_load_permanent  — z_cg   (уровень ЦТ пролётного строения)
        z_load_temporary  — z_road (уровень проезжей части)

      Сейсмические массы — постоянная часть:
        z_mass_X_perm  — z_hinge (из «Масс»: r_mx_z)
        z_mass_Y_perm  — z_cg    (из «Масс»: r_my_z)
        z_mass_Z_perm  — z_cg    (из «Масс»: r_mz_z)

      Сейсмические массы — временная часть:
        z_mass_X_temp  — z_hinge (из «Масс»: r_mx_t_z)
        z_mass_Y_temp  — z_road  (из «Масс»: r_my_t_z)
        z_mass_Z_temp  — z_road  (из «Масс»: r_mz_t_z)

    Единицы: масса — тс·с²/м; нагрузка — тс.
    Силы трения не используются.
    """
    pier_name:      str
    bearing_number: Optional[int]   # номер ОЧ в Excel (1–4)
    side:           str             # 'right' (+Y) | 'left' (−Y)
    frame_number:   int             # 1 или 2

    # ── Координаты (x, y — локальные, без аффинного преобразования) ─────────
    x:   float                      # вдоль пролёта
    y:   float                      # поперёк (+Y правая, −Y левая)

    # ── z-отметки вертикальных нагрузок ─────────────────────────────────────
    z_load_permanent: Optional[float]  # z_cg   — уровень ЦТ пролётного строения
    z_load_temporary: Optional[float]  # z_road — уровень проезжей части

    # ── z-отметки сейсмических масс ─────────────────────────────────────────
    # Постоянные массы
    z_mass_X_perm:  Optional[float]  # z_hinge (r_mx_z)
    z_mass_Y_perm:  Optional[float]  # z_cg    (r_my_z)
    z_mass_Z_perm:  Optional[float]  # z_cg    (r_mz_z)

    # Временные массы
    z_mass_X_temp:  Optional[float]  # z_hinge (r_mx_t_z)
    z_mass_Y_temp:  Optional[float]  # z_road  (r_my_t_z)
    z_mass_Z_temp:  Optional[float]  # z_road  (r_mz_t_z)

    # ── Вертикальные нагрузки (тс) ───────────────────────────────────────────
    load_permanent: float = 0.0     # R_пост @ z_load_permanent = z_cg
    load_temporary: float = 0.0     # R_врем @ z_load_temporary = z_road

    # ── Сейсмические массы, постоянная часть (тс·с²/м) ──────────────────────
    mass_X_permanent: float = 0.0   # @ z_mass_X_perm (z_hinge)
    mass_Y_permanent: float = 0.0   # @ z_mass_Y_perm (z_cg)
    mass_Z_permanent: float = 0.0   # @ z_mass_Z_perm (z_cg)

    # ── Сейсмические массы, временная часть (тс·с²/м) ───────────────────────
    mass_X_temporary: float = 0.0   # @ z_mass_X_temp (z_hinge)
    mass_Y_temporary: float = 0.0   # @ z_mass_Y_temp (z_road)
    mass_Z_temporary: float = 0.0   # @ z_mass_Z_temp (z_road)

    # ── Тип ОЧ ──────────────────────────────────────────────────────────────
    bearing_type_X: str = 'fixed'   # fixed / movable
    bearing_type_Y: str = 'fixed'

    # ── Номера узлов КЭ-модели (заполняются в Части 1 по coord_index) ────────
    # None означает, что узел с нужными координатами не найден в модели.
    node_id_load_permanent: Optional[int] = None  # узел @ (x, y, z_load_permanent)
    node_id_load_temporary: Optional[int] = None  # узел @ (x, y, z_load_temporary)
    node_id_mass_X_perm:    Optional[int] = None  # узел @ (x, y, z_mass_X_perm)
    node_id_mass_Y_perm:    Optional[int] = None  # узел @ (x, y, z_mass_Y_perm)
    node_id_mass_Z_perm:    Optional[int] = None  # узел @ (x, y, z_mass_Z_perm)
    node_id_mass_X_temp:    Optional[int] = None  # узел @ (x, y, z_mass_X_temp)
    node_id_mass_Y_temp:    Optional[int] = None  # узел @ (x, y, z_mass_Y_temp)
    node_id_mass_Z_temp:    Optional[int] = None  # узел @ (x, y, z_mass_Z_temp)

    # ── Псевдонимы ───────────────────────────────────────────────────────────
    @property
    def z_cg(self) -> Optional[float]:
        """Псевдоним → z_load_permanent (уровень ЦТ пролёта)."""
        return self.z_load_permanent

    @property
    def z_road(self) -> Optional[float]:
        """Псевдоним → z_load_temporary (уровень проезжей части)."""
        return self.z_load_temporary

    @property
    def z_hinge(self) -> Optional[float]:
        """Псевдоним → z_mass_X_perm (уровень шарнира ОЧ)."""
        return self.z_mass_X_perm


@dataclass
class PierLoadAssignment:
    """
    Результат Части 1 для одной опоры:
    все точки приложения нагрузок и масс с координатами.

    Передаётся в Часть 2 (генерация команд .mct) без изменений.
    """
    pier_name:   str
    load_points: list[LoadPoint] = field(default_factory=list)
    warnings:    list[str]       = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры модуль 3 часть 2
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NodeMassEntry:
    """Горизонтальная сейсмическая масса одного узла от одного источника."""
    node_id:   int
    z:         float   # Z-координата узла, м
    mass_x:    float   # масса по X, тс·с²/м
    mass_y:    float   # масса по Y, тс·с²/м  (= mass_x для изотропной зоны)
    source:    str     # 'вода' | 'разжижение'
    elem_type: str     # _ELEM_TYPE_*


@dataclass
class FluidMassResult:
    """
    Результат Части 2 для одной опоры.

    node_masses — список NodeMassEntry (может быть несколько записей на один
                  узел, если он граничит с несколькими элементами; суммируются
                  при записи в .mct).
    warnings    — диагностические сообщения (незаданные площади, пустые зоны и т.д.)
    """
    pier_name:   str
    node_masses: list[NodeMassEntry] = field(default_factory=list)
    warnings:    list[str]           = field(default_factory=list)

    def total_mass_x(self) -> float:
        return sum(e.mass_x for e in self.node_masses)

    def total_mass_y(self) -> float:
        return sum(e.mass_y for e in self.node_masses)

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных Модуля 3, Часть 3 — боковое давление грунта
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ElemPressureEntry:
    """
    Трапециевидная эпюра бокового давления грунта на один элемент.

    q_i, q_j — интенсивность нагрузки (тс/м) в узлах i и j соответственно.
    Направление задаётся полем direction ('y' или 'z').

    Знак нагрузки положительный: направление приложения (ось Y или Z
    локальной системы) определяется при генерации .mct командой *BEAM-LOAD.
    """
    elem_id:    int
    node_i:     int       # id узла i (нижний)
    node_j:     int       # id узла j (верхний)
    z_i:        float     # Z-координата узла i, м
    z_j:        float     # Z-координата узла j, м
    width_i:    float     # ширина сечения в узле i, м
    width_j:    float     # ширина сечения в узле j, м
    pressure_i: float     # активное давление грунта в узле i, тс/м²
    pressure_j: float     # активное давление грунта в узле j, тс/м²
    q_i:        float     # нагрузка в узле i = pressure_i * width_i, тс/м
    q_j:        float     # нагрузка в узле j = pressure_j * width_j, тс/м
    direction:  str       # 'y' или 'z'
    elem_type:  str       # _ELEM_TYPE_PILE / _ELEM_TYPE_FOOTING / _ELEM_TYPE_BODY


@dataclass
class LateralPressureResult:
    """
    Результат Части 3 Модуля 3 для одной опоры.

    entries_y — элементы с боковым давлением по оси Y.
    entries_z — элементы с боковым давлением по оси Z.
    warnings  — диагностические сообщения.
    """
    pier_name: str
    entries_y: list[ElemPressureEntry] = field(default_factory=list)
    entries_z: list[ElemPressureEntry] = field(default_factory=list)
    warnings:  list[str]              = field(default_factory=list)

    def total_force_y(self) -> float:
        """Суммарная равнодействующая по Y (трапеции → среднее * длина)."""
        return sum(
            (e.q_i + e.q_j) / 2.0 * abs(e.z_j - e.z_i)
            for e in self.entries_y
        )

    def total_force_z(self) -> float:
        """Суммарная равнодействующая по Z."""
        return sum(
            (e.q_i + e.q_j) / 2.0 * abs(e.z_j - e.z_i)
            for e in self.entries_z
        )

# ═══════════════════════════════════════════════════════════════════════════════
#  Структуры данных результата
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ElemPressureEntry:
    """
    Трапециевидная эпюра бокового давления грунта на один элемент.

    q_i, q_j — интенсивность нагрузки (тс/м) в узлах i и j соответственно.
    Направление задаётся полем direction ('y' или 'z').

    Знак нагрузки положительный: направление приложения (ось Y или Z
    локальной системы) определяется при генерации .mct командой *BEAM-LOAD.
    """
    elem_id:   int
    node_i:    int           # id узла i (нижний)
    node_j:    int           # id узла j (верхний)
    z_i:       float         # Z-координата узла i, м
    z_j:       float         # Z-координата узла j, м
    width_i:   float         # ширина сечения в узле i, м
    width_j:   float         # ширина сечения в узле j, м
    pressure_i: float        # активное давление грунта в узле i, тс/м²
    pressure_j: float        # активное давление грунта в узле j, тс/м²
    q_i:       float         # нагрузка в узле i = pressure_i * width_i, тс/м
    q_j:       float         # нагрузка в узле j = pressure_j * width_j, тс/м
    direction: str           # 'y' или 'z'
    elem_type: str           # _ELEM_TYPE_*


@dataclass
class LateralPressureResult:
    """
    Результат Части 3 для одной опоры.

    entries_y — элементы с боковым давлением по оси Y.
    entries_z — элементы с боковым давлением по оси Z.
    warnings  — диагностические сообщения.
    """
    pier_name: str
    entries_y: list[ElemPressureEntry] = field(default_factory=list)
    entries_z: list[ElemPressureEntry] = field(default_factory=list)
    warnings:  list[str]              = field(default_factory=list)

    def total_force_y(self) -> float:
        """Суммарная равнодействующая по Y (трапеции → среднее * длина)."""
        return sum(
            (e.q_i + e.q_j) / 2.0 * abs(e.z_j - e.z_i)
            for e in self.entries_y
        )

    def total_force_z(self) -> float:
        """Суммарная равнодействующая по Z."""
        return sum(
            (e.q_i + e.q_j) / 2.0 * abs(e.z_j - e.z_i)
            for e in self.entries_z
        )
# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 1 — мешинг одной части стержня
# ═══════════════════════════════════════════════════════════════════════════════
from additional_functions import _coord_key, _z_coordinates_for_zone, _add_ts_group_element
from data_structures import PierModel, SectionZone, Node, Element, PierGeometry, ShaftPartResult


def _mesh_shaft_part(
        model: PierModel,
        zones: list[SectionZone],
        z_bottom: float,
        z_top_part: float,
        mesh_step: float,
        node_offset: int,
        elem_offset: int,
        coord_index: dict,
) -> tuple[int, int, int]:
    """
    Мешит одну часть стержня (ростверк / стойку / ригель).

    zones       — список SectionZone для этой части (отсортированы по z_top возрастанию)
    z_bottom    — Z низа части
    z_top_part  — Z верха части
    mesh_step   — шаг разбивки, м
    node_offset — стартовый офсет нумерации узлов для этой части
    elem_offset — стартовый офсет нумерации элементов для этой части
    coord_index — общий индекс координат опоры

    Возвращает: (кол-во новых узлов, кол-во новых элементов, node_id верхнего узла)
    """
    if not zones:
        raise ValueError('Список зон не может быть пустым')

    # Убедимся, что зоны отсортированы по z_top
    sorted_zones = sorted(zones, key=lambda z: z.zone_z_top)

    # Счётчики для офсетов внутри части
    node_local_counter = 0
    elem_local_counter = 0
    new_nodes_count = 0
    new_elems_count = 0

    def next_node_id() -> int:
        nonlocal node_local_counter
        nid = node_offset + node_local_counter
        node_local_counter += 1
        return nid

    def next_elem_id() -> int:
        nonlocal elem_local_counter
        eid = elem_offset + elem_local_counter
        elem_local_counter += 1
        return eid

    # Переопределяем get_or_create для локальных счётчиков
    def _get_or_create(x: float, y: float, z: float) -> tuple[int, bool]:
        """Возвращает (node_id, is_new)."""
        nonlocal new_nodes_count
        key = _coord_key(x, y, z)
        if key in coord_index:
            return coord_index[key], False
        nid = next_node_id()
        model.nodes[nid] = Node(node_id=nid, x=x, y=y, z=z)
        coord_index[key] = nid
        new_nodes_count += 1
        return nid, True

    current_z_bottom = z_bottom

    for zone in sorted_zones:
        zone_z_top = min(zone.zone_z_top, z_top_part)  # защита от выхода за верх части

        z_coords = _z_coordinates_for_zone(current_z_bottom, zone_z_top, mesh_step)

        for k in range(len(z_coords) - 1):
            node_i_id, _ = _get_or_create(0.0, 0.0, z_coords[k])
            node_j_id, _ = _get_or_create(0.0, 0.0, z_coords[k + 1])

            eid = next_elem_id()
            model.elements[eid] = Element(
                elem_id=eid,
                node_i=node_i_id,
                node_j=node_j_id,
                section_number=zone.section_number,
                material_number=zone.material_number,
            )
            new_elems_count += 1

            if zone.use_ts_group and zone.ts_group_number is not None:
                _add_ts_group_element(model, zone.ts_group_number, eid)

        current_z_bottom = zone_z_top

    # Получаем id узла на самом верху части (уже существует — создан в последнем пролёте)
    top_node_key = _coord_key(0.0, 0.0, z_top_part)
    top_node_id = coord_index[top_node_key]

    return new_nodes_count, new_elems_count, top_node_id


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная функция Части 1
# ═══════════════════════════════════════════════════════════════════════════════

def generate_shaft(pier: PierGeometry) -> tuple[PierModel, list[ShaftPartResult]]:
    """
    Генерирует КЭ-модель стержня опоры (ростверк → стойка → ригель).

    Принимает PierGeometry с заполненными:
        footing_zones, footing_z_top, footing_mesh_step,
        column_zones,  column_z_top,  column_mesh_step,
        crossbeam_zones, crossbeam_z_top, crossbeam_mesh_step,
        node_offset_*, elem_offset_*.

    Возвращает (PierModel, list[ShaftPartResult]).
    Не печатает ничего — вывод делает main через print_shaft_report().
    """
    model = PierModel(pier_name=pier.pier_name)
    coord_index: dict = {}  # общий индекс координат для всей опоры
    shaft_results: list[ShaftPartResult] = []

    # ── Нижняя граница ростверка ─────────────────────────────────────────────

    parts = [
        dict(
            name='Ростверк',
            zones=pier.footing_zones,
            z_bottom=0.0,
            z_top=pier.footing_z_top,
            mesh_step=pier.footing_mesh_step,
            node_offset=pier.node_offset_footing,
            elem_offset=pier.elem_offset_footing,
        ),
        dict(
            name='Стойка',
            zones=pier.column_zones,
            z_bottom=pier.footing_z_top,
            z_top=pier.column_z_top,
            mesh_step=pier.column_mesh_step,
            node_offset=pier.node_offset_column,
            elem_offset=pier.elem_offset_column,
        ),
        dict(
            name='Ригель',
            zones=pier.crossbeam_zones,
            z_bottom=pier.column_z_top,
            z_top=pier.crossbeam_z_top,
            mesh_step=pier.crossbeam_mesh_step,
            node_offset=pier.node_offset_crossbeam,
            elem_offset=pier.elem_offset_crossbeam,
        ),
    ]

    for part in parts:
        if part['z_top'] is None:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: z_top не задан')
        if not part['zones']:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: список зон пуст')

        length = part['z_top'] - part['z_bottom']
        if length <= 0:
            raise ValueError(
                f'[{pier.pier_name}] {part["name"]}: '
                f'z_bottom={part["z_bottom"]:.4f} >= z_top={part["z_top"]:.4f}')

        n_nodes, n_elems, _ = _mesh_shaft_part(
            model=model,
            zones=part['zones'],
            z_bottom=part['z_bottom'],
            z_top_part=part['z_top'],
            mesh_step=part['mesh_step'],
            node_offset=part['node_offset'],
            elem_offset=part['elem_offset'],
            coord_index=coord_index,
        )

        shaft_results.append(ShaftPartResult(
            name=part['name'],
            z_bottom=part['z_bottom'],
            z_top=part['z_top'],
            n_nodes=n_nodes,
            n_elems=n_elems,
            elem_offset=part['elem_offset'],
        ))

    return model, shaft_results
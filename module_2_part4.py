"""
module_2_part4.py — Часть 4 модуля 2: RigidLink, Constraints, Hinges

RigidLink
---------
  RL-1 (сваи→ростверк):
    Мастер-узел — узел низа ростверка (z = 0.0, x=0, y=0).
    Слейв-узлы  — узлы верха свай (наивысшая z у каждой сваи, x≠0 или y≠0).
    Создаётся только если задан pile_mct_file_path.

  RL-2 (ригель→подферменники):
    Мастер-узел — узел верха ригеля (z = crossbeam_z_top, x=0, y=0).
    Слейв-узлы  — узлы низа подферменников (z = pad_z_bottom у каждой рамки,
                  один низ подферменника на рамку, две точки ±Y).

Constraints
-----------
  Если сваи есть: для каждого узла низа свай — закрепление Dz + Rz
                  (вектор: 0 0 1 0 0 1 0)
  Если свай нет:  низ ростверка (z=0, x=0, y=0) — полное защемление
                  (вектор: 1 1 1 1 1 1 1)

Hinges
------
  Для каждого элемента опорной части (уже записанного в model.frame_rls):
    - Верхний конец (j): Mz всегда свободен; Fx, Fz, Mx, My всегда закреплены.
    - Fy зависит от типа ОЧ поперёк (global Y):
        movable_Y → Fy свободен (True)
        fixed_Y   → Fy закреплён (False)
  Формат release_j: (Fx, Fy, Fz, Mx, My, Mz) = (F, FY, F, F, F, T)
  где F = False, T = True.

  Нижний конец (i) всегда полностью закреплён: (F,F,F,F,F,F).

Структуры данных
----------------
  RigidLink     — dataclass с master_node_id и slave_node_ids.
  Constraint    — dataclass с node_id и вектором из 7 bool.
  Hinge (FrameRLS) — уже существует в data_structures, здесь только перезаписывается
                     для ясности (функция _build_hinge_rls).
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from data_structures import PierGeometry, PierModel, FrameRLS, RigidLink, Constraint, CONSTRAINT_DZ_RZ, CONSTRAINT_FULL
from additional_functions import _coord_key, _footing_bottom_node, _pile_top_nodes, _crossbeam_top_node, \
    _pad_bottom_nodes, _pile_bottom_nodes


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 4 — RigidLink
# ═══════════════════════════════════════════════════════════════════════════════

def build_rigid_links(
        model: PierModel,
        pier: PierGeometry,
) -> list[RigidLink]:
    """
    Строит список RigidLink для опоры.

    RL-1: Ростверк ↔ верх свай  (только если pile_mct_file_path задан).
    RL-2: Верх ригеля ↔ низ подферменников (всегда, если рамки существуют).

    Возвращает список из 1–2 объектов RigidLink (порядок: RL-1 первый, если есть).
    """
    result: list[RigidLink] = []
    link_id = 1

    # ── RL-1: низ ростверка (мастер) ↔ верх свай (слейвы) ───────────────────
    has_piles = bool(pier.pile_mct_file_path)
    if has_piles:
        master_id = _footing_bottom_node(model)
        if master_id is None:
            raise RuntimeError(
                f'[{pier.pier_name}] RL-1: узел низа ростверка (0,0,0) не найден. '
                f'Убедитесь, что generate_shaft() выполнена до build_rigid_links().')

        slaves = _pile_top_nodes(model, pier)
        if not slaves:
            raise RuntimeError(
                f'[{pier.pier_name}] RL-1: задан pile_mct_file_path, '
                f'но узлы свай не найдены в модели. '
                f'Убедитесь, что load_piles_for_pier() выполнена до build_rigid_links().')

        result.append(RigidLink(
            link_id=link_id,
            master_node_id=master_id,
            slave_node_ids=slaves,
            description='Ростверк ↔ верх свай',
        ))
        link_id += 1

    # ── RL-2: верх ригеля (мастер) ↔ низ подферменников (слейвы) ────────────
    master_cb = _crossbeam_top_node(model, pier)
    slaves_pads = _pad_bottom_nodes(model, pier)

    if master_cb is not None and slaves_pads:
        result.append(RigidLink(
            link_id=link_id,
            master_node_id=master_cb,
            slave_node_ids=slaves_pads,
            description='Верх ригеля ↔ низ подферменников',
        ))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 4 — Constraints
# ═══════════════════════════════════════════════════════════════════════════════

def build_constraints(
        model: PierModel,
        pier: PierGeometry,
) -> list[Constraint]:
    """
    Формирует граничные условия опоры.

    Если сваи заданы:
        Для каждого узла низа свай — Dz + Rz (вектор 0 0 1 0 0 1 0).
    Если свай нет:
        Узел низа ростверка (0, 0, 0) — полное защемление (1 1 1 1 1 1 1).
    """
    has_piles = bool(pier.pile_mct_file_path)

    if has_piles:
        bot_nodes = _pile_bottom_nodes(model, pier)
        if not bot_nodes:
            raise RuntimeError(
                f'[{pier.pier_name}] Constraints: pile_mct_file_path задан, '
                f'но узлы низа свай не найдены.')
        return [
            Constraint(
                node_id=nid,
                flags=CONSTRAINT_DZ_RZ,
                description='Низ сваи: Dz + Rz',
            )
            for nid in bot_nodes
        ]
    else:
        master_id = _footing_bottom_node(model)
        if master_id is None:
            raise RuntimeError(
                f'[{pier.pier_name}] Constraints: узел низа ростверка (0,0,0) не найден.')
        return [
            Constraint(
                node_id=master_id,
                flags=CONSTRAINT_FULL,
                description='Низ ростверка: полное защемление',
            )
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#  Часть 4 — Hinges (шарниры в ОЧ)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_hinge_rls(movable_y: bool) -> tuple:
    """
    Формирует release_j для элемента опорной части.

    Правило (верхний конец j):
      Fx  — всегда закреплён (False)
      Fy  — свободен если movable_Y ('movable'), иначе закреплён
      Fz  — всегда закреплён (False)
      Mx  — всегда закреплён (False)
      My  — всегда закреплён (False)   ← My НЕ освобождается в ОЧ
      Mz  — всегда свободен  (True)

    Нижний конец (i) — всегда (F,F,F,F,F,F).
    """
    return (False, movable_y, False, False, False, True)


def build_hinges(
        model: PierModel,
        pier: PierGeometry,
) -> dict[int, FrameRLS]:
    """
    Переформирует шарниры в элементах опорных частей.

    Читает уже записанные в model.frame_rls записи (заполненные Частью 2)
    и перестраивает release_j по правилам Части 4:
      - Mz всегда свободен.
      - Fx, Fz, Mx, My всегда закреплены.
      - Fy: movable (True) если тип_Y == 'movable', иначе False.

    Метаданные о типе ОЧ берутся из существующего release_j Части 2:
      Часть 2 записывала:  release_j = (movable_x, movable_y, False, False, True, True)
      Часть 4 перезаписывает: release_j = (False, movable_y, False, False, False, True)

    Обновляет model.frame_rls «на месте» и возвращает тот же словарь.
    """
    for elem_id, rls in model.frame_rls.items():
        # Часть 2 сохраняла movable_y в позиции [1] release_j
        movable_y: bool = rls.release_j[1]

        model.frame_rls[elem_id] = FrameRLS(
            elem_id=elem_id,
            release_i=(False, False, False, False, False, False),
            release_j=_build_hinge_rls(movable_y),
        )

    return model.frame_rls


# ═══════════════════════════════════════════════════════════════════════════════
#  Публичная точка входа Части 4
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Part4Result:
    """Полный результат Части 4 (для main и Модуля 5)."""
    rigid_links: list[RigidLink]          = field(default_factory=list)
    constraints: list[Constraint]         = field(default_factory=list)
    hinges:      dict[int, FrameRLS]      = field(default_factory=dict)
    errors:      list[str]                = field(default_factory=list)


def generate_part4(
        model: PierModel,
        pier: PierGeometry,
) -> Part4Result:
    """
    Выполняет Часть 4: строит RigidLink, Constraints и перезаписывает Hinges.

    Предполагает, что generate_shaft(), generate_frames() и (если нужно)
    load_piles_for_pier() уже выполнены и model полностью заполнен.

    Не печатает ничего. Вывод делает main через print_part4_report().
    """
    result = Part4Result()

    try:
        result.rigid_links = build_rigid_links(model, pier)
    except RuntimeError as exc:
        result.errors.append(f'RigidLink: {exc}')

    try:
        result.constraints = build_constraints(model, pier)
    except RuntimeError as exc:
        result.errors.append(f'Constraints: {exc}')

    result.hinges = build_hinges(model, pier)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Вывод в main
# ═══════════════════════════════════════════════════════════════════════════════

def print_part4_report(result: Part4Result, model: PierModel) -> None:
    """Печатает сводку по RigidLink, Constraints и Hinges."""

    print('\n' + '═' * 60)
    print('  ЧАСТЬ 4 — RigidLink / Constraints / Hinges')
    print('═' * 60)

    # ── Ошибки ──────────────────────────────────────────────────────────────
    if result.errors:
        print('\n  ⚠ ОШИБКИ:')
        for err in result.errors:
            print(f'    • {err}')

    # ── RigidLink ────────────────────────────────────────────────────────────
    print(f'\n  RigidLink ({len(result.rigid_links)} шт.):')
    if not result.rigid_links:
        print('    (нет)')
    for rl in result.rigid_links:
        master_node = model.nodes.get(rl.master_node_id)
        master_str = (
            f'({master_node.x:.3f}, {master_node.y:.3f}, {master_node.z:.3f})'
            if master_node else '?'
        )
        print(f'    RL-{rl.link_id}: {rl.description}')
        print(f'      Мастер-узел: #{rl.master_node_id} {master_str}')
        print(f'      Слейв-узлы : {rl.slave_node_ids}  '
              f'(кол-во: {len(rl.slave_node_ids)})')

    # ── Constraints ──────────────────────────────────────────────────────────
    print(f'\n  Constraints ({len(result.constraints)} шт.):')
    if not result.constraints:
        print('    (нет)')
    for i, c in enumerate(result.constraints):
        node = model.nodes.get(c.node_id)
        xyz = (
            f'({node.x:.3f}, {node.y:.3f}, {node.z:.3f})'
            if node else '?'
        )
        flags_str = '\t'.join(str(f) for f in c.flags)
        if i == 0:
            # Однократно выводим шапку
            header = 'Dx\tDy\tDz\tRx\tRy\tRz\tТип'
            print(f'    Узел  {header}')
        print(f'    #{c.node_id} {xyz}\t{flags_str}  — {c.description}')

    # ── Hinges ───────────────────────────────────────────────────────────────
    print(f'\n  Hinges (шарниры в ОЧ, {len(result.hinges)} шт.):')
    if not result.hinges:
        print('    (нет)')
    else:
        print('    Elem  release_i (Fx Fy Fz Mx My Mz)   '
              'release_j (Fx Fy Fz Mx My Mz)')
        for elem_id, rls in sorted(result.hinges.items()):
            ri = ' '.join('1' if v else '0' for v in rls.release_i)
            rj = ' '.join('1' if v else '0' for v in rls.release_j)
            fy_note = '(Fy своб.)' if rls.release_j[1] else '(Fy закр.)'
            print(f'    #{elem_id:<5}  [{ri}]          [{rj}]  {fy_note}')

    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Тесты Части 4
# ═══════════════════════════════════════════════════════════════════════════════

def _make_test_model_no_piles() -> tuple['PierModel', 'PierGeometry']:
    """
    Строит минимальную модель без свай для тестов.
    Ростверк (0→2), стойка (2→5), ригель (5→6).
    Одна рамка с подферменниками y=±1.0, pad_z_bottom=5.5, pad_z_top=6.0.
    Два элемента ОЧ: правый (fixed/fixed), левый (fixed/movable).
    """
    from data_structures import (
        PierModel, PierGeometry, Node, Element, FrameRLS,
        SectionZone, FrameParameters,
    )

    pier = PierGeometry(
        pier_name='TEST_NO_PILES',
        footing_z_top=2.0,
        column_z_top=5.0,
        crossbeam_z_top=6.0,
        pile_mct_file_path=None,
    )
    pier.frame1 = FrameParameters(
        frame_number=1,
        x_coordinate=0.0,
        pad_y_half_width=1.0,
        pad_y_right=1.0,
        pad_y_left=1.0,
        pad_z_bottom=5.5,
        pad_z_top=6.0,
    )

    model = PierModel(pier_name='TEST_NO_PILES')

    # Узлы стержня (x=0, y=0)
    for nid, z in enumerate([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.5, 6.0], start=1):
        model.nodes[nid] = Node(node_id=nid, x=0.0, y=0.0, z=z)

    # Узлы рамки: низ и верх подферменников (y=±1)
    # Узел 9: x=0, y=+1, z=5.5 (низ правого подферменника)
    # Узел 10: x=0, y=-1, z=5.5 (низ левого подферменника)
    # Узлы верха подферменников совпадают с узлом 8 (z=6.0) по z — но разные y:
    # Узел 11: x=0, y=+1, z=6.0; Узел 12: x=0, y=-1, z=6.0
    model.nodes[9]  = Node(node_id=9,  x=0.0, y= 1.0, z=5.5)
    model.nodes[10] = Node(node_id=10, x=0.0, y=-1.0, z=5.5)
    model.nodes[11] = Node(node_id=11, x=0.0, y= 1.0, z=6.0)
    model.nodes[12] = Node(node_id=12, x=0.0, y=-1.0, z=6.0)

    # FrameRLS от Части 2: правая ОЧ fixed/fixed, левая ОЧ fixed/movable
    # release_j = (movable_x, movable_y, False, False, True, True)
    model.frame_rls[201] = FrameRLS(  # правая ОЧ (fixed Y)
        elem_id=201,
        release_i=(False, False, False, False, False, False),
        release_j=(False, False, False, False, True, True),  # movable_y=False
    )
    model.frame_rls[202] = FrameRLS(  # левая ОЧ (movable Y)
        elem_id=202,
        release_i=(False, False, False, False, False, False),
        release_j=(False, True, False, False, True, True),   # movable_y=True
    )

    return model, pier


def _make_test_model_with_piles() -> tuple['PierModel', 'PierGeometry']:
    """
    Строит минимальную модель со сваями для тестов.
    Ростверк (0→2). Сваи: 3 шт., каждая от z=-5 до z=0 (нижний узел z=-5).
    node_offset_piles = 1001.
    """
    from data_structures import PierModel, PierGeometry, Node, FrameRLS

    pier = PierGeometry(
        pier_name='TEST_WITH_PILES',
        footing_z_top=2.0,
        column_z_top=5.0,
        crossbeam_z_top=6.0,
        pile_mct_file_path='/fake/path/piles.mct',
        node_offset_piles=1001,
    )

    model = PierModel(pier_name='TEST_WITH_PILES')

    # Узлы стержня
    for nid, z in enumerate([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0], start=1):
        model.nodes[nid] = Node(node_id=nid, x=0.0, y=0.0, z=z)

    # 3 сваи: (x=1,y=0), (x=-1,y=0), (x=0,y=1)
    # Каждая: z от -5 до 0, 2 узла
    pile_configs = [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0)]
    nid = 1001
    for px, py in pile_configs:
        # Нижний узел (низ сваи)
        model.nodes[nid] = Node(node_id=nid, x=px, y=py, z=-5.0)
        nid += 1
        # Верхний узел (верх сваи, = z низа ростверка = 0.0)
        model.nodes[nid] = Node(node_id=nid, x=px, y=py, z=0.0)
        nid += 1

    return model, pier


# ── Тест 1: RL-1 не создаётся если свай нет ──────────────────────────────────

def test_no_piles_no_rl1() -> bool:
    """Без свай должен быть только RL-2 (или ни одного, если нет рамок)."""
    model, pier = _make_test_model_no_piles()
    result = generate_part4(model, pier)

    # Нет свай → нет RL-1
    has_pile_rl = any('свай' in rl.description for rl in result.rigid_links)
    ok = not has_pile_rl
    print(f'  ТЕСТ 1 (нет свай → нет RL-1): {"✓" if ok else "✗"}')
    return ok


# ── Тест 2: RL-2 — мастер-узел верха ригеля, слейвы — низ подферменников ────

def test_rl2_master_and_slaves() -> bool:
    """RL-2: мастер z=crossbeam_z_top; слейвы z=pad_z_bottom, y≠0."""
    model, pier = _make_test_model_no_piles()
    result = generate_part4(model, pier)

    rl2_list = [rl for rl in result.rigid_links if 'ригеля' in rl.description]
    if not rl2_list:
        print('  ТЕСТ 2 (RL-2 существует): ✗ — RL-2 не создан')
        return False

    rl2 = rl2_list[0]
    master_node = model.nodes[rl2.master_node_id]
    ok_master = math.isclose(master_node.z, pier.crossbeam_z_top, abs_tol=1e-6)
    ok_slaves = len(rl2.slave_node_ids) == 2  # два подферменника (±Y)

    ok = ok_master and ok_slaves
    print(f'  ТЕСТ 2 (RL-2 мастер/слейвы): {"✓" if ok else "✗"} '
          f'(master.z={master_node.z}, slaves={rl2.slave_node_ids})')
    return ok


# ── Тест 3: Constraint без свай — полное защемление низа ростверка ───────────

def test_constraint_no_piles_full() -> bool:
    """Без свай — 1 Constraint на узел (0,0,0) с флагами (1,1,1,1,1,1,0)."""
    model, pier = _make_test_model_no_piles()
    result = generate_part4(model, pier)

    ok_count = (len(result.constraints) == 1)
    if not ok_count:
        print(f'  ТЕСТ 3 (Constraint без свай): ✗ — ожидался 1, получено {len(result.constraints)}')
        return False

    c = result.constraints[0]
    node = model.nodes[c.node_id]
    ok_xyz = (math.isclose(node.x, 0.0, abs_tol=1e-6) and
               math.isclose(node.y, 0.0, abs_tol=1e-6) and
               math.isclose(node.z, 0.0, abs_tol=1e-6))
    ok_flags = (c.flags == CONSTRAINT_FULL)

    ok = ok_xyz and ok_flags
    print(f'  ТЕСТ 3 (Constraint без свай — полное защемл.): {"✓" if ok else "✗"} '
          f'(node=#{c.node_id}, flags={c.flags})')
    return ok


# ── Тест 4: Constraints со сваями — Dz+Rz на каждом низу сваи ───────────────

def test_constraint_with_piles_dz_rz() -> bool:
    """Со сваями — по 1 Constraint на каждый низ сваи, флаги = CONSTRAINT_DZ_RZ."""
    model, pier = _make_test_model_with_piles()
    result = generate_part4(model, pier)

    n_bot = _pile_bottom_nodes(model, pier)
    ok_count = (len(result.constraints) == len(n_bot) == 3)
    ok_flags = all(c.flags == CONSTRAINT_DZ_RZ for c in result.constraints)

    ok = ok_count and ok_flags
    print(f'  ТЕСТ 4 (Constraints со сваями): {"✓" if ok else "✗"} '
          f'(кол-во={len(result.constraints)}, флаги верны={ok_flags})')
    return ok


# ── Тест 5: RL-1 — мастер низ ростверка, слейвы верх свай ───────────────────

def test_rl1_with_piles() -> bool:
    """RL-1: мастер z=0; слейвы — верх свай (z=0, x/y ≠ 0)."""
    model, pier = _make_test_model_with_piles()
    result = generate_part4(model, pier)

    rl1_list = [rl for rl in result.rigid_links if 'свай' in rl.description]
    if not rl1_list:
        print('  ТЕСТ 5 (RL-1 со сваями): ✗ — RL-1 не создан')
        return False

    rl1 = rl1_list[0]
    master_node = model.nodes[rl1.master_node_id]
    ok_master = (math.isclose(master_node.x, 0.0, abs_tol=1e-6) and
                 math.isclose(master_node.y, 0.0, abs_tol=1e-6) and
                 math.isclose(master_node.z, 0.0, abs_tol=1e-6))
    ok_slaves = (len(rl1.slave_node_ids) == 3)  # 3 сваи

    ok = ok_master and ok_slaves
    print(f'  ТЕСТ 5 (RL-1 мастер/слейвы): {"✓" if ok else "✗"} '
          f'(master.z={master_node.z}, n_slaves={len(rl1.slave_node_ids)})')
    return ok


# ── Тест 6: Hinges — правила release_j ───────────────────────────────────────

def test_hinges_release_rules() -> bool:
    """
    Проверяет release_j после build_hinges:
      - Elem 201 (fixed Y):   release_j = (F,F,F,F,F,T)
      - Elem 202 (movable Y): release_j = (F,T,F,F,F,T)
    """
    model, pier = _make_test_model_no_piles()
    result = generate_part4(model, pier)

    rls201 = result.hinges.get(201)
    rls202 = result.hinges.get(202)

    ok201 = (rls201 is not None and
             rls201.release_j == (False, False, False, False, False, True))
    ok202 = (rls202 is not None and
             rls202.release_j == (False, True, False, False, False, True))

    ok = ok201 and ok202
    print(f'  ТЕСТ 6 (Hinges release_j):')
    print(f'    Elem 201 (fixed Y):   {"✓" if ok201 else "✗"}  '
          f'{rls201.release_j if rls201 else "не найден"}')
    print(f'    Elem 202 (movable Y): {"✓" if ok202 else "✗"}  '
          f'{rls202.release_j if rls202 else "не найден"}')
    return ok


# ── Тест 7: release_i всегда нулевой ─────────────────────────────────────────

def test_hinges_release_i_always_zero() -> bool:
    """release_i всегда (F,F,F,F,F,F) для всех ОЧ."""
    model, pier = _make_test_model_no_piles()
    result = generate_part4(model, pier)

    zero = (False, False, False, False, False, False)
    ok = all(rls.release_i == zero for rls in result.hinges.values())
    print(f'  ТЕСТ 7 (release_i = нулевой): {"✓" if ok else "✗"}')
    return ok


def run_all_tests() -> None:
    """Запускает все тесты Части 4 и выводит итог."""
    print('\n' + '─' * 60)
    print('  Запуск тестов Части 4')
    print('─' * 60)

    tests = [
        test_no_piles_no_rl1,
        test_rl2_master_and_slaves,
        test_constraint_no_piles_full,
        test_constraint_with_piles_dz_rz,
        test_rl1_with_piles,
        test_hinges_release_rules,
        test_hinges_release_i_always_zero,
    ]

    results = [t() for t in tests]
    n_pass = sum(results)
    n_total = len(results)

    print('─' * 60)
    print(f'  Итог: {n_pass}/{n_total} тестов пройдено '
          f'{"✓ ВСЕ" if n_pass == n_total else "✗ ЕСТЬ ОШИБКИ"}')
    print('─' * 60)


# ═══════════════════════════════════════════════════════════════════════════════
#  main — демонстрация
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    run_all_tests()

    # ── Демонстрация на модели без свай ──────────────────────────────────────
    print('\n' + '═' * 60)
    print('  Демонстрация: опора БЕЗ свай')
    model_demo, pier_demo = _make_test_model_no_piles()
    result_demo = generate_part4(model_demo, pier_demo)
    print_part4_report(result_demo, model_demo)

    # ── Демонстрация на модели со сваями ─────────────────────────────────────
    print('═' * 60)
    print('  Демонстрация: опора СО сваями')
    model_pile, pier_pile = _make_test_model_with_piles()
    result_pile = generate_part4(model_pile, pier_pile)
    print_part4_report(result_pile, model_pile)

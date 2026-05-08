"""
Модуль 3, Часть 1: Соответствие листа «Массы» и листа «Плеть» рамкам опоры.

Для каждой опоры строит список LoadPoint — точек приложения масс и нагрузок
с готовыми координатами (x, y, z) и значениями масс/сил.

─────────────────────────────────────────────────────────────────────────────
Логика соответствия
─────────────────────────────────────────────────────────────────────────────
Рамки опоры:
  • Если опора встречается в листе «Массы» 1 раз → у неё одна рамка (frame1).
  • Если 2 раза → две рамки: 1-е вхождение → frame1, 2-е → frame2.

Правая / левая ОЧ:
  • MassesRow.right_* / BearingPlaneRow.right_* → подферменник +Y (pad_y_right)
  • MassesRow.left_*  / BearingPlaneRow.left_*  → подферменник −Y (−pad_y_left)

Связь MassesRow ↔ BearingPlaneRow:
  • По span_group_row_start / span_group_row_end — диапазон строк данных
    в листе «Плеть» (1-based, считая только строки данных, без разделителей
    «Плеть N», примечаний и пустых строк).
  • Внутри диапазона ищем строку, где r_bearing_no == MassesRow.right_bearing_number
    (и l_bearing_no == MassesRow.left_bearing_number).

Отметки приложения нагрузок и масс (z-уровни):
  ┌─────────────────────────────────┬────────────────────────────────────────┐
  │ Величина                        │ z-отметка                              │
  ├─────────────────────────────────┼────────────────────────────────────────┤
  │ R_пост  (вертикальная нагр.)    │ z_cg     — уровень ЦТ пролётного стр. │
  │ R_врем  (вертикальная нагр.)    │ z_road   — уровень проезжей части      │
  ├─────────────────────────────────┼────────────────────────────────────────┤
  │ mX_пост (сейсм. масса)          │ z_hinge  — из листа «Массы» (r_mx_z)  │
  │ mY_пост (сейсм. масса)          │ z_cg     — из листа «Массы» (r_my_z)  │
  │ mZ_пост (сейсм. масса)          │ z_cg     — из листа «Массы» (r_mz_z)  │
  │ mX_врем (сейсм. масса)          │ z_hinge  — из листа «Массы» (r_mx_t_z)│
  │ mY_врем (сейсм. масса)          │ z_road   — из листа «Массы» (r_my_t_z)│
  │ mZ_врем (сейсм. масса)          │ z_road   — из листа «Массы» (r_mz_t_z)│
  └─────────────────────────────────┴────────────────────────────────────────┘

  R_пост прикладывается на уровне ЦТ пролётного строения (z_cg).
  R_врем прикладывается на уровне проезжей части (z_road).
  Постоянные массы mY, mZ — на уровне ЦТ пролётного строения (z_cg).
  Временные массы mY, mZ — на уровне проезжей части (z_road).
  Все mX — на уровне z_hinge.
  Силы трения (F_тр) не используются.
─────────────────────────────────────────────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import Optional

from additional_functions import (
    _plety_rows_for_pier, _find_plety_row, _build_load_point, _lookup_node_id,
)
from data_structures import (
    MassesRow, BearingPlaneRow, PierGeometry, FrameParameters,
    PierLoadAssignment,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Основные функции Части 1
# ═══════════════════════════════════════════════════════════════════════════════

def build_load_assignments(
    pier:            PierGeometry,
    all_masses_rows: list[MassesRow],
    all_plety_rows:  list[BearingPlaneRow],
    coord_index:     Optional[dict] = None,
) -> PierLoadAssignment:
    """
    Строит PierLoadAssignment для одной опоры.

    Алгоритм:
      1. Фильтруем строки «Масс» по pier_name → 1 или 2 строки
         (1-я → frame1, 2-я → frame2).
      2. Для каждой строки масс определяем соответствующую рамку.
      3. Для каждой стороны (right / left) ищем строку «Плети» по
         span_group_row_start/end и bearing_number.
      4. Строим LoadPoint с координатами и значениями.
      5. Если передан coord_index (локальный индекс из PierGeometryResult) —
         резолвим node_id для каждой z-отметки; узлы, не найденные в модели,
         дают None и предупреждение в консоль.

    coord_index — словарь {_coord_key(x_local, y_local, z_local): node_id},
    берётся напрямую из PierGeometryResult.coord_index. Координаты в нём
    локальные (до аффинного преобразования), что совпадает с lp.x / lp.y.
    """
    result = PierLoadAssignment(pier_name=pier.pier_name)

    # ── Шаг 1: строки «Масс» для этой опоры в порядке появления ─────────────
    pier_masses: list[MassesRow] = [
        m for m in all_masses_rows if m.pier_name == pier.pier_name
    ]

    if not pier_masses:
        result.warnings.append(
            f'[{pier.pier_name}] нет строк в листе «Массы» — нагрузки не назначены')
        return result

    if len(pier_masses) > 2:
        result.warnings.append(
            f'[{pier.pier_name}] найдено {len(pier_masses)} строк в «Массах» '
            f'(ожидалось 1 или 2) — обработаны первые две')
        pier_masses = pier_masses[:2]

    # ── Шаг 2: сопоставление строки масс → рамка ─────────────────────────────
    # 1-е вхождение → frame1, 2-е → frame2
    frame_assignments: list[tuple[MassesRow, FrameParameters, int]] = []

    for occurrence_idx, masses_row in enumerate(pier_masses):
        frame_number = occurrence_idx + 1           # 1 или 2
        frame = pier.frame1 if frame_number == 1 else pier.frame2

        if frame is None:
            result.warnings.append(
                f'[{pier.pier_name}] frame{frame_number} не задана, '
                f'но в «Массах» есть {frame_number}-е вхождение — пропущено')
            continue

        frame_assignments.append((masses_row, frame, frame_number))

    # ── Шаги 3–4: строим LoadPoint для каждой (рамка × сторона) ─────────────
    for masses_row, frame, frame_number in frame_assignments:

        candidate_plety = _plety_rows_for_pier(all_plety_rows, pier.pier_name)

        if not candidate_plety:
            result.warnings.append(
                f'[{pier.pier_name}] frame{frame_number}: '
                f'нет строк «Плети» для опоры {pier.pier_name}')

        for side in ('right', 'left'):
            bearing_number = (masses_row.right_bearing_number if side == 'right'
                              else masses_row.left_bearing_number)

            plety_row = _find_plety_row(candidate_plety, bearing_number, side)

            if plety_row is None:
                result.warnings.append(
                    f'[{pier.pier_name}] frame{frame_number} {side}: '
                    f'строка «Плети» с bearing_no={bearing_number} не найдена')
                continue

            lp = _build_load_point(
                pier=pier,
                frame=frame,
                masses_row=masses_row,
                plety_row=plety_row,
                side=side,
                frame_number=frame_number,
            )

            # ── Шаг 5: резолвинг node_id по coord_index ──────────────────────
            if coord_index is not None:
                lp_label = (
                    f'frame{frame_number} {side} ОЧ№{lp.bearing_number}'
                )
                lp.node_id_load_permanent = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_load_permanent,
                    f'{lp_label} R_пост(z_cg)', pier.pier_name,
                )
                lp.node_id_load_temporary = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_load_temporary,
                    f'{lp_label} R_врем(z_road)', pier.pier_name,
                )
                lp.node_id_mass_X_perm = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_X_perm,
                    f'{lp_label} mX_пост(z_hinge)', pier.pier_name,
                )
                lp.node_id_mass_Y_perm = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_Y_perm,
                    f'{lp_label} mY_пост(z_cg)', pier.pier_name,
                )
                lp.node_id_mass_Z_perm = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_Z_perm,
                    f'{lp_label} mZ_пост(z_cg)', pier.pier_name,
                )
                lp.node_id_mass_X_temp = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_X_temp,
                    f'{lp_label} mX_врем(z_hinge)', pier.pier_name,
                )
                lp.node_id_mass_Y_temp = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_Y_temp,
                    f'{lp_label} mY_врем(z_road)', pier.pier_name,
                )
                lp.node_id_mass_Z_temp = _lookup_node_id(
                    coord_index, lp.x, lp.y, lp.z_mass_Z_temp,
                    f'{lp_label} mZ_врем(z_road)', pier.pier_name,
                )

            result.load_points.append(lp)

    return result


def build_all_load_assignments(
    piers:           list[PierGeometry],
    all_masses_rows: list[MassesRow],
    all_plety_rows:  list[BearingPlaneRow],
    coord_indices:   Optional[dict[str, dict]] = None,
) -> dict[str, PierLoadAssignment]:
    """
    Строит PierLoadAssignment для всех опор проекта.

    Возвращает словарь {pier_name: PierLoadAssignment}.
    Опоры с calculate=False пропускаются.

    coord_indices — опциональный словарь {pier_name: coord_index},
    где coord_index берётся из PierGeometryResult.coord_index.
    Если передан — для каждого LoadPoint резолвятся node_id.
    """
    return {
        pier.pier_name: build_load_assignments(
            pier, all_masses_rows, all_plety_rows,
            coord_index=coord_indices.get(pier.pier_name) if coord_indices else None,
        )
        for pier in piers
        if pier.calculate
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Вспомогательные функции форматирования
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_z(z: Optional[float]) -> str:
    """Форматирует z-отметку: три знака после запятой или '—'."""
    return f'{z:.3f}' if z is not None else '—'


def _tbl_header(col_widths: dict, header_cells: list[str], title: str) -> tuple[int, str]:
    """Печатает заголовок таблицы, возвращает (total_width, separator_line)."""
    sep    = '─'
    widths = list(col_widths.values())
    total  = sum(widths) + len(widths) * 3 - 1
    line   = sep * total
    heads  = ' | '.join(c.center(w) for c, w in zip(header_cells, widths))
    print(f'\n    {title:^{total}}')
    print(f'    {line}')
    print(f'    {heads}')
    print(f'    {line}')
    return total, line


# ═══════════════════════════════════════════════════════════════════════════════
#  Табличный вывод результатов (для main в mct_generator.py)
# ═══════════════════════════════════════════════════════════════════════════════

# Таблица 1: нагрузки — R_пост @ z_cg, R_врем @ z_road
_COL_LOADS = {
    'рамка':   6,
    'ОЧ':      4,
    'сторона': 12,
    'x':        8,
    'y':        8,
    'z':        8,    # z_cg для R_пост, z_road для R_врем
    'узел':     6,    # node_id
    'знач.':   13,
    'описание': 32,
}

# Таблица 2: массы — каждая строка на своей z
_COL_MASSES = {
    'рамка':   6,
    'ОЧ':      4,
    'сторона': 12,
    'x':        8,
    'y':        8,
    'z':        8,    # индивидуальная z для каждой массы
    'узел':     6,    # node_id
    'масса':   16,
    'описание': 32,
}


def print_module3_report(assignments: dict[str, PierLoadAssignment]) -> None:
    """
    Выводит результаты Модуля 3 (Часть 1) в консоль в табличном виде.

    Для каждой опоры — две таблицы:

      Таблица 1. Нагрузки от опорных частей.
        R_пост прикладывается на уровне ЦТ пролётного строения (z_cg).
        R_врем прикладывается на уровне проезжей части (z_road).
        Силы трения не выводятся.

      Таблица 2. Сейсмические массы.
        Каждая масса указана на своей отметке из листа «Массы»:
          mX_п, mX_в → z_hinge
          mY_п, mZ_п → z_cg    (уровень ЦТ пролётного строения)
          mY_в, mZ_в → z_road  (уровень проезжей части)

    Вызывается из main() в mct_generator.py.
    """
    for pier_name, assignment in assignments.items():
        print(f'\n  {"═" * 72}')
        print(f'  Опора [{pier_name}] — нагрузки и массы (Модуль 3, Часть 1)')
        print(f'  {"═" * 72}')

        if assignment.warnings:
            for w in assignment.warnings:
                print(f'    ⚠  {w}')

        if not assignment.load_points:
            print('    (нет точек приложения нагрузок)')
            continue

        wl = list(_COL_LOADS.values())
        wm = list(_COL_MASSES.values())

        # ── Таблица 1: Нагрузки ──────────────────────────────────────────────
        # R_пост — на уровне z_cg  (ЦТ пролётного строения).
        # R_врем — на уровне z_road (проезжая часть).
        # Каждая ОЧ выводится двумя строками: постоянная и временная нагрузка.
        header_loads = [
            'Рамка', '№ОЧ', 'Сторона', 'x, м', 'y, м',
            'z, м', 'Узел',
            'Знач., тс',
            'Описание',
        ]
        _, line1 = _tbl_header(
            _COL_LOADS, header_loads,
            'Таблица 1. Нагрузки от опорных частей  [R_пост @ z_cg | R_врем @ z_road]',
        )

        for lp in assignment.load_points:
            side_lbl = '+Y прав.' if lp.side == 'right' else '−Y лев.'
            x_str    = f'{lp.x:.3f}'
            y_str    = f'{lp.y:+.3f}'
            type_str = f'X={lp.bearing_type_X} Y={lp.bearing_type_Y}'

            def _load_row(val: float, z_val: Optional[float],
                          node_id: Optional[int],
                          descr: str, first: bool = False) -> None:
                node_str = str(node_id) if node_id is not None else '—'
                cells = [
                    (str(lp.frame_number)   if first else '').center(wl[0]),
                    (str(lp.bearing_number) if first else '').center(wl[1]),
                    (side_lbl               if first else '').ljust(wl[2]),
                    (x_str                  if first else '').rjust(wl[3]),
                    (y_str                  if first else '').rjust(wl[4]),
                    _fmt_z(z_val).rjust(wl[5]),
                    node_str.center(wl[6]),
                    f'{val:+.3f}'.rjust(wl[7]),
                    descr.ljust(wl[8]),
                ]
                print(f'    {" | ".join(cells)}')

            _load_row(lp.load_permanent, lp.z_load_permanent,
                      lp.node_id_load_permanent,
                      f'R_пост @ z_cg   ({type_str})', first=True)
            _load_row(lp.load_temporary, lp.z_load_temporary,
                      lp.node_id_load_temporary,
                      'R_врем @ z_road')

        print(f'    {line1}')

        # ── Таблица 2: Сейсмические массы ────────────────────────────────────
        # Каждая масса на своей z-отметке из листа «Массы»:
        #   mX_п, mX_в  → z_hinge
        #   mY_п, mZ_п  → z_cg  (уровень ЦТ пролётного строения)
        #   mY_в, mZ_в  → z_road (уровень проезжей части)
        header_masses = [
            'Рамка', '№ОЧ', 'Сторона', 'x, м', 'y, м',
            'z, м', 'Узел',
            'Масса, тс·с²/м',
            'Описание  (z из листа «Массы»)',
        ]
        _, line2 = _tbl_header(
            _COL_MASSES, header_masses,
            'Таблица 2. Сейсмические массы  '
            '[mX @ z_hinge | mY_п/mZ_п @ z_cg | mY_в/mZ_в @ z_road]',
        )

        for lp in assignment.load_points:
            side_lbl = '+Y прав.' if lp.side == 'right' else '−Y лев.'
            x_str    = f'{lp.x:.3f}'
            y_str    = f'{lp.y:+.3f}'

            # (z-отметка, node_id, значение, описание, показать_координаты_ОЧ)
            rows = [
                (lp.z_mass_X_perm, lp.node_id_mass_X_perm, lp.mass_X_permanent, 'mX_пост  @ z_hinge',  True),
                (lp.z_mass_Y_perm, lp.node_id_mass_Y_perm, lp.mass_Y_permanent, 'mY_пост  @ z_cg',     False),
                (lp.z_mass_Z_perm, lp.node_id_mass_Z_perm, lp.mass_Z_permanent, 'mZ_пост  @ z_cg',     False),
                (lp.z_mass_X_temp, lp.node_id_mass_X_temp, lp.mass_X_temporary, 'mX_врем  @ z_hinge',  False),
                (lp.z_mass_Y_temp, lp.node_id_mass_Y_temp, lp.mass_Y_temporary, 'mY_врем  @ z_road',   False),
                (lp.z_mass_Z_temp, lp.node_id_mass_Z_temp, lp.mass_Z_temporary, 'mZ_врем  @ z_road',   False),
            ]

            for z_val, node_id, mass_val, descr, first in rows:
                node_str = str(node_id) if node_id is not None else '—'
                cells = [
                    (str(lp.frame_number)   if first else '').center(wm[0]),
                    (str(lp.bearing_number) if first else '').center(wm[1]),
                    (side_lbl               if first else '').ljust(wm[2]),
                    (x_str                  if first else '').rjust(wm[3]),
                    (y_str                  if first else '').rjust(wm[4]),
                    _fmt_z(z_val).rjust(wm[5]),
                    node_str.center(wm[6]),
                    f'{mass_val:.4f}'.rjust(wm[7]),
                    descr.ljust(wm[8]),
                ]
                print(f'    {" | ".join(cells)}')

        print(f'    {line2}')

        # ── Справка по z-уровням ──────────────────────────────────────────────
        print()
        for lp in assignment.load_points:
            side_lbl = '+Y прав.' if lp.side == 'right' else '−Y лев.'
            print(
                f'    Рамка {lp.frame_number} ОЧ №{lp.bearing_number} {side_lbl}:'
                f'  z_cg={_fmt_z(lp.z_load_permanent)} м  (R_пост)'
                f'  |  z_road={_fmt_z(lp.z_load_temporary)} м  (R_врем)'
                f'  |  z_hinge={_fmt_z(lp.z_mass_X_perm)} м  (mX_п, mX_в)'
                f'  |  z_cg={_fmt_z(lp.z_mass_Y_perm)} м  (mY_п, mZ_п)'
                f'  |  z_road={_fmt_z(lp.z_mass_Y_temp)} м  (mY_в, mZ_в)'
            )


def print_load_assignments(assignments: dict[str, PierLoadAssignment]) -> None:
    """Псевдоним для обратной совместимости — вызывает print_module3_report."""
    print_module3_report(assignments)
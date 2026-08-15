/**
 * Modal de detalhamento de chamadas (Bootstrap): filtros, agrupamento por mês,
 * lista virtualizada leve (sem libs).
 *
 * @typedef {Object} AttendanceRecord
 * @property {string} [data_iso] YYYY-MM-DD
 * @property {string} [data_fmt] dd/mm/yyyy
 * @property {string} [horario]
 * @property {string} [turma_nome]
 * @property {boolean} [presente]
 * @property {string} [status_chamada] presente|falta|justificada|atestado...
 */

(function () {
  'use strict';

  var ROW_H = 42;
  var MONTH_HDR_H = 48;

  /** @param {string} s */
  function parseDataFmt(s) {
    if (!s || typeof s !== 'string') return null;
    var m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s.trim());
    if (!m) return null;
    var d = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), 12, 0, 0);
    return isNaN(d.getTime()) ? null : d;
  }

  /**
   * @param {AttendanceRecord} r
   * @returns {{ date: Date, dateKey: string } | null}
   */
  function recordDate(r) {
    if (r.data_iso) {
      var d = new Date(String(r.data_iso) + 'T12:00:00');
      if (!isNaN(d.getTime()))
        return { date: d, dateKey: r.data_iso };
    }
    var d2 = parseDataFmt(r.data_fmt || '');
    if (!d2) return null;
    var y = d2.getFullYear();
    var mo = String(d2.getMonth() + 1).padStart(2, '0');
    var da = String(d2.getDate()).padStart(2, '0');
    return { date: d2, dateKey: y + '-' + mo + '-' + da };
  }

  var WD = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
  var MO = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];

  /** @param {Date} d */
  function tooltipLong(d) {
    return WD[d.getDay()] + ', ' + d.getDate() + ' de ' + MO[d.getMonth()] + ' de ' + d.getFullYear();
  }

  /** @param {Date} d */
  function diaMes(d) {
    return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0');
  }

  /**
   * @param {AttendanceRecord} r
   * @returns {AttendanceRecord}
   */
  function normalizeRecord(r) {
    var rd = recordDate(r);
    var date = rd ? rd.date : null;
    var nr = Object.assign({}, r);
    if (date) {
      nr._date = date;
      nr._diaMes = diaMes(date);
      nr._tooltip = tooltipLong(date);
    } else {
      nr._diaMes = (r.data_fmt || '').split('/').slice(0, 2).join('/') || '—';
      nr._tooltip = r.data_fmt || '';
    }
    var st = (r.status_chamada || '').toLowerCase();
    if (st.indexOf('justif') >= 0 || st.indexOf('atest') >= 0) nr._badge = 'outro';
    else if (r.presente === true || st === 'presente') nr._badge = 'presente';
    else nr._badge = 'falta';
    return nr;
  }

  /**
   * @param {object} filters
   * @param {number|string} filters.year — ano ou 'all'
   * @param {string} filters.status — all|presentes|faltas
   * @param {string} filters.turma — '' ou nome exato
   * @param {string} [filters.dateFrom] yyyy-mm-dd
   * @param {string} [filters.dateTo]
   */
  function filterRecords(records, filters) {
    var y = filters.year;
    var st = filters.status || 'all';
    var turma = filters.turma || '';
    var df = filters.dateFrom || '';
    var dt = filters.dateTo || '';
    return records.filter(function (raw) {
      var r = normalizeRecord(raw);
      var rd = recordDate(r);
      if (!rd) return false;
      if (y !== 'all' && Number(y) !== rd.date.getFullYear()) return false;
      if (df && rd.dateKey < df) return false;
      if (dt && rd.dateKey > dt) return false;
      if (turma && String(r.turma_nome || '') !== turma) return false;
      if (st === 'presentes' && r._badge !== 'presente') return false;
      if (st === 'faltas' && r._badge !== 'falta') return false;
      return true;
    });
  }

  function pctClass(p) {
    if (p >= 70) return 'ok';
    if (p >= 50) return 'mid';
    return 'low';
  }

  /** @param {number} presentes @param {number} dias */
  function roundPct(presentes, dias) {
    if (!dias) return 0;
    return Math.round((presentes / dias) * 1000) / 10;
  }

  /**
   * Agrupa por mês: totais do período sem filtro de status (baseRows) vs linhas visíveis.
   * @param {AttendanceRecord[]} baseRowsRaw — filterRecords(..., { ..., status: 'all' })
   * @param {AttendanceRecord[]} visibleRaw — resultado do filtro completo
   * @param {{ collapsed: Record<string, boolean>, defaultExpanded: boolean }} opts
   */
  function groupAttendanceByMonth(baseRowsRaw, visibleRaw, opts) {
    var collapsed = opts.collapsed || {};
    var defExp = opts.defaultExpanded !== false;

    /** @type Record<string, AttendanceRecord[]> */
    var byMonthAll = {};
    baseRowsRaw.forEach(function (raw) {
      var r = normalizeRecord(raw);
      if (!r._date) return;
      var k =
        r._date.getFullYear() +
        '-' +
        String(r._date.getMonth() + 1).padStart(2, '0');
      if (!byMonthAll[k]) byMonthAll[k] = [];
      byMonthAll[k].push(r);
    });

    var visible = visibleRaw.map(function (x) {
      return normalizeRecord(x);
    });
    /** @type Record<string, AttendanceRecord[]> */
    var byMonthVis = {};
    visible.forEach(function (r) {
      if (!r._date) return;
      var k =
        r._date.getFullYear() +
        '-' +
        String(r._date.getMonth() + 1).padStart(2, '0');
      if (!byMonthVis[k]) byMonthVis[k] = [];
      byMonthVis[k].push(r);
    });

    var keys = Object.keys(byMonthVis).sort().reverse();
    if (!keys.length) return { months: [], flatItems: [], totals: { aulas: 0, presencas: 0, pct: 0 } };

    /** @param {AttendanceRecord[]} arr */
    function stats(arr) {
      var d = arr.length;
      var p = arr.filter(function (x) {
        return x._badge === 'presente';
      }).length;
      return { aulas: d, presencas: p, pct: roundPct(p, d) };
    }

    var months = keys.map(function (k) {
      var parts = k.split('-');
      var monthIx = Number(parts[1]) - 1;
      var label = (MO[monthIx] || k).toUpperCase() + ' ' + parts[0];
      var allArr = byMonthAll[k] || [];
      var visArr = byMonthVis[k] || [];
      var stAll = stats(allArr);
      var stVis = stats(visArr);
      visArr.sort(function (a, b) {
        return (b._date && a._date ? b._date - a._date : 0);
      });
      var expanded =
        collapsed[k] === undefined ? defExp : !collapsed[k];
      return {
        key: k,
        label: label,
        expanded: expanded,
        statsVisible: stVis,
        statsTotal: stAll,
        rows: visArr,
      };
    });

    var flatItems = [];
    months.forEach(function (m) {
      flatItems.push({ type: 'month', month: m, height: MONTH_HDR_H });
      if (m.expanded) {
        m.rows.forEach(function (row) {
          flatItems.push({ type: 'row', row: row, height: ROW_H });
        });
      }
    });

    var totalAulas = visible.length;
    var totalPres = visible.filter(function (x) {
      return normalizeRecord(x)._badge === 'presente';
    }).length;
    var totals = {
      aulas: totalAulas,
      presencas: totalPres,
      pct: roundPct(totalPres, totalAulas),
    };

    return { months: months, flatItems: flatItems, totals: totals };
  }

  function distinctTurmas(records) {
    var s = {};
    records.forEach(function (r) {
      var t = String(r.turma_nome || '').trim();
      if (t) s[t] = true;
    });
    return Object.keys(s).sort();
  }

  function distinctYears(records) {
    var s = {};
    records.forEach(function (r) {
      var rd = recordDate(r);
      if (rd) s[String(rd.date.getFullYear())] = true;
    });
    return Object.keys(s)
      .map(Number)
      .sort(function (a, b) {
        return b - a;
      });
  }

  function buildYearOptions(records, currentYear) {
    var ys = distinctYears(records);
    var opts = [{ v: 'all', t: 'Todos' }];
    ys.forEach(function (y) {
      opts.push({ v: String(y), t: String(y) });
    });
    if (opts.length === 1) opts.push({ v: String(currentYear), t: String(currentYear) });
    return opts;
  }

  /** Escapa CSV */
  function csvEscape(v) {
    if (v == null) return '';
    var s = String(v);
    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function exportCsv(rows) {
    var headers = ['data_iso', 'data', 'horario', 'turma', 'status'];
    var lines = [headers.join(',')];
    rows.forEach(function (r) {
      var n = normalizeRecord(r);
      var rd = recordDate(n);
      var iso = rd ? rd.dateKey : '';
      var status =
        n._badge === 'presente'
          ? 'Presente'
          : n._badge === 'falta'
            ? 'Falta'
            : n.status_chamada || 'Outro';
      lines.push(
        [
          csvEscape(iso),
          csvEscape(n.data_fmt || ''),
          csvEscape(n.horario || ''),
          csvEscape(n.turma_nome || ''),
          csvEscape(status),
        ].join(',')
      );
    });
    var blob = new Blob([lines.join('\n')], {
      type: 'text/csv;charset=utf-8;',
    });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'chamadas.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function el(html) {
    var t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  /**
   * @param {HTMLElement} modalEl
   */
  function initModal(modalEl) {
    var id = modalEl.id || '';
    var jsonEl = document.getElementById(
      'attendance-data-' + id.replace('modalFreqJudoDetalhe', '')
    );
    if (!jsonEl) return;

    var records = [];
    try {
      records = JSON.parse((jsonEl.textContent || '').trim() || '[]') || [];
    } catch (e) {
      records = [];
    }

    var currentYear = new Date().getFullYear();
    var openerBtn = null;
    document.addEventListener(
      'click',
      function (e) {
        var t = e.target && e.target.closest('[data-bs-target="#' + id + '"]');
        if (t) openerBtn = t;
      },
      true
    );

    var filters = {
      year: String(currentYear),
      status: 'all',
      turma: '',
      dateFrom: '',
      dateTo: '',
    };
    var collapsed = {};

    var selYear = modalEl.querySelector('.afd-filter-year');
    var selStatus = modalEl.querySelector('.afd-filter-status');
    var selTurma = modalEl.querySelector('.afd-filter-turma');
    var inpFrom = modalEl.querySelector('.afd-filter-date-from');
    var inpTo = modalEl.querySelector('.afd-filter-date-to');
    var btnClear = modalEl.querySelector('.afd-filter-clear');
    var btnExportCsv = modalEl.querySelector('.afd-export-csv');
    var btnAccordion = modalEl.querySelector('.afd-filters-mobile-toggle');
    var filtersCollapse = modalEl.querySelector('.afd-filters-collapsible');
    var statAulas = modalEl.querySelector('.afd-stat-aulas');
    var statPres = modalEl.querySelector('.afd-stat-presencas');
    var statPct = modalEl.querySelector('.afd-stat-pct');
    var footCount = modalEl.querySelector('.afd-footer-count');
    var emptyEl = modalEl.querySelector('.afd-empty-state');
    var virtualInner = modalEl.querySelector('.afd-virtual-inner');
    var parentModalSel = modalEl.getAttribute('data-parent-modal');

    if (
      !selYear ||
      !selStatus ||
      !selTurma ||
      !inpFrom ||
      !inpTo ||
      !btnClear ||
      !virtualInner ||
      !emptyEl ||
      !statAulas ||
      !statPres ||
      !statPct ||
      !footCount
    ) {
      return;
    }

    function computeDefaultExpanded() {
      return filters.year === 'all' || String(filters.year) === String(currentYear);
    }

    function rebuildTurmaOptions() {
      var yn = filters.year === 'all' ? 'all' : Number(filters.year);
      var subset = records.filter(function (r) {
        var rd = recordDate(r);
        if (!rd) return false;
        if (yn === 'all') return true;
        return rd.date.getFullYear() === yn;
      });
      var turmas = distinctTurmas(subset);
      selTurma.innerHTML =
        '<option value="">Todas</option>' +
        turmas
          .map(function (t) {
            return (
              '<option value="' +
              String(t).replace(/"/g, '&quot;') +
              '">' +
              t +
              '</option>'
            );
          })
          .join('');
      if (filters.turma && turmas.indexOf(filters.turma) < 0) filters.turma = '';
      selTurma.value = filters.turma;
    }

    function populateYears() {
      var opts = buildYearOptions(records, currentYear);
      selYear.innerHTML = opts
        .map(function (o) {
          return '<option value="' + o.v + '">' + o.t + '</option>';
        })
        .join('');
      if (
        !opts.some(function (o) {
          return o.v === filters.year;
        })
      )
        filters.year = String(currentYear);
      selYear.value = filters.year;
    }

    function filtersActive() {
      return (
        filters.status !== 'all' ||
        !!filters.turma ||
        !!filters.dateFrom ||
        !!filters.dateTo ||
        filters.year !== String(currentYear)
      );
    }

    function syncClearVisibility() {
      var active = filtersActive();
      btnClear.classList.toggle('d-none', !active);
    }

    /** @param {boolean} statusFiltered — presentes/faltas */
    function renderMonthSubtitle(m, statusFiltered) {
      var v = m.statsVisible;
      var t = m.statsTotal;
      var cls = 'afd-month-pct--' + pctClass(v.pct);
      var base =
        v.aulas +
        ' aula' +
        (v.aulas !== 1 ? 's' : '') +
        ' · ' +
        v.presencas +
        ' presença' +
        (v.presencas !== 1 ? 's' : '') +
        ' · <span class="' +
        cls +
        '">' +
        v.pct +
        '%</span>';
      if (
        statusFiltered &&
        (v.aulas !== t.aulas || v.presencas !== t.presencas)
      ) {
        base +=
          ' <span class="text-muted fw-normal">(' +
          t.aulas +
          ' aulas · ' +
          t.presencas +
          ' presenças · ' +
          t.pct +
          '% total)</span>';
      }
      return base;
    }

    function render() {
      var filtersBase = Object.assign({}, filters, { status: 'all' });
      var baseRows = filterRecords(records, filtersBase);
      var visible = filterRecords(records, filters);
      var grouped = groupAttendanceByMonth(baseRows, visible, {
        collapsed: collapsed,
        defaultExpanded: computeDefaultExpanded(),
      });

      var statusFiltered =
        filters.status === 'presentes' || filters.status === 'faltas';

      statAulas.textContent = grouped.totals.aulas;
      statPres.textContent = grouped.totals.presencas;
      statPct.textContent = grouped.totals.pct + '%';
      statPct.className =
        'afd-stat-pct afd-stat-pct--' + pctClass(grouped.totals.pct);

      footCount.textContent =
        'Mostrando ' +
        visible.length +
        ' de ' +
        records.length +
        ' registros';

      syncClearVisibility();

      if (!records.length) {
        emptyEl.classList.remove('d-none');
        emptyEl.querySelector('.afd-empty-title').textContent =
          'Nenhuma chamada registrada ainda para este aluno.';
        emptyEl.querySelector('.afd-empty-clear').classList.add('d-none');
        virtualInner.innerHTML = '';
        return;
      }

      if (!visible.length) {
        emptyEl.classList.remove('d-none');
        emptyEl.querySelector('.afd-empty-title').textContent =
          'Nenhuma chamada encontrada com os filtros atuais.';
        emptyEl.querySelector('.afd-empty-clear').classList.remove('d-none');
        virtualInner.innerHTML = '';
        return;
      }

      emptyEl.classList.add('d-none');

      virtualInner.innerHTML = '';

      var fragDesktop = document.createDocumentFragment();
      var fragMobile = document.createDocumentFragment();

      grouped.flatItems.forEach(function (item, idx) {
        if (item.type === 'month') {
          var m = item.month;
          var hdr = el(
            '<div class="afd-month-header" role="button" tabindex="0" aria-expanded="' +
              m.expanded +
              '" aria-controls="afd-month-' +
              id +
              '-' +
              m.key +
              '" id="afd-month-h-' +
              id +
              '-' +
              m.key +
              '">' +
              '<span>' +
              m.label +
              '</span>' +
              '<span class="afd-month-stats">' +
              renderMonthSubtitle(m, statusFiltered) +
              '</span>' +
              '<span class="afd-chevron bi bi-chevron-down small" aria-hidden="true"></span></div>'
          );
          var chev = hdr.querySelector('.afd-chevron');
          if (chev) chev.style.transform = m.expanded ? 'rotate(180deg)' : '';
          hdr.addEventListener('click', function () {
            collapsed[m.key] = m.expanded;
            render();
          });
          hdr.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' || ev.key === ' ') {
              ev.preventDefault();
              collapsed[m.key] = m.expanded;
              render();
            }
          });
          var body = document.createElement('div');
          body.className = 'afd-month-body';
          body.id = 'afd-month-' + id + '-' + m.key;
          fragDesktop.appendChild(hdr);
          fragDesktop.appendChild(body);
        }
      });

      /* Desktop: uma tabela por mês para thead consistente */
      grouped.months.forEach(function (m) {
        if (!m.expanded || !m.rows.length) return;
        var bodies = fragDesktop.querySelectorAll('.afd-month-body');
        var bodyEl = Array.prototype.find.call(bodies, function (b) {
          return b.id === 'afd-month-' + id + '-' + m.key;
        });
        if (!bodyEl) return;
        var wrap = document.createElement('div');
        wrap.className = 'afd-desktop-table table-responsive';
        wrap.innerHTML =
          '<table class="table table-sm align-middle mb-0"><thead class="table-light"><tr><th scope="col">Data</th><th scope="col">Horário</th><th scope="col">Turma</th><th scope="col" class="text-end">Chamada</th></tr></thead><tbody class="afd-tbody-' +
          m.key +
          '"></tbody></table>';
        var tb = wrap.querySelector('tbody');
        m.rows.forEach(function (row, ix) {
          var badge =
            row._badge === 'presente'
              ? '<span class="afd-badge-call afd-badge-presente"><span class="afd-dot"></span>Presente</span>'
              : row._badge === 'falta'
                ? '<span class="afd-badge-call afd-badge-falta"><span class="afd-dot"></span>Falta</span>'
                : '<span class="afd-badge-call afd-badge-outro"><span class="afd-dot"></span>' +
                  (row.status_chamada || 'Outro') +
                  '</span>';
          var hora =
            row.horario && String(row.horario).trim()
              ? '<span>' +
                String(row.horario).replace(/</g, '') +
                '</span>'
              : '<span class="afd-time-empty">—</span>';
          var tr = el(
            '<tr class="afd-row-hover afd-row-striped" title="' +
              String(row._tooltip || '').replace(/"/g, '&quot;') +
              '"><th scope="row" title="' +
              String(row._tooltip || '').replace(/"/g, '&quot;') +
              '">' +
              row._diaMes +
              '</th><td>' +
              hora +
              '</td><td>' +
              String(row.turma_nome || '').replace(/</g, '') +
              '</td><td class="text-end">' +
              badge +
              '</td></tr>'
          );
          tb.appendChild(tr);

          var card = el(
            '<div class="afd-class-card"><div><div class="afd-class-card-date" title="' +
              String(row._tooltip || '').replace(/"/g, '&quot;') +
              '">' +
              row._diaMes +
              '</div><div class="small text-muted">' +
              (row.horario && String(row.horario).trim()
                ? String(row.horario).replace(/</g, '')
                : '<span class="afd-time-empty">—</span>') +
              '</div><div class="small">' +
              String(row.turma_nome || '').replace(/</g, '') +
              '</div></div><div>' +
              badge +
              '</div></div>'
          );
          fragMobile.appendChild(card);
        });
        bodyEl.appendChild(wrap);
      });

      var mobileWrap = document.createElement('div');
      mobileWrap.className = 'afd-mobile-cards';
      while (fragMobile.firstChild) mobileWrap.appendChild(fragMobile.firstChild);

      virtualInner.appendChild(fragDesktop);
      virtualInner.appendChild(mobileWrap);
    }

    function onFilterChange() {
      filters.year = selYear.value;
      filters.status = selStatus.value;
      filters.turma = selTurma.value;
      filters.dateFrom = inpFrom.value || '';
      filters.dateTo = inpTo.value || '';
      rebuildTurmaOptions();
      render();
    }

    populateYears();
    rebuildTurmaOptions();
    selYear.addEventListener('change', onFilterChange);
    selStatus.addEventListener('change', onFilterChange);
    selTurma.addEventListener('change', onFilterChange);
    inpFrom.addEventListener('change', onFilterChange);
    inpTo.addEventListener('change', onFilterChange);

    btnClear.addEventListener('click', function () {
      filters.year = String(currentYear);
      filters.status = 'all';
      filters.turma = '';
      filters.dateFrom = '';
      filters.dateTo = '';
      collapsed = {};
      selYear.value = filters.year;
      selStatus.value = 'all';
      inpFrom.value = '';
      inpTo.value = '';
      rebuildTurmaOptions();
      render();
    });

    emptyEl.querySelector('.afd-empty-clear').addEventListener('click', function () {
      btnClear.click();
    });

    if (btnAccordion && filtersCollapse) {
      btnAccordion.addEventListener('click', function () {
        filtersCollapse.classList.toggle('show');
        var open = filtersCollapse.classList.contains('show');
        btnAccordion.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }

    if (btnExportCsv) {
      btnExportCsv.addEventListener('click', function () {
        var rows = filterRecords(records, filters);
        exportCsv(rows);
      });
    }

    modalEl.addEventListener('show.bs.modal', function () {
      document.body.classList.add('attendance-child-open');
    });

    modalEl.addEventListener('shown.bs.modal', function () {
      populateYears();
      rebuildTurmaOptions();
      render();
      var backs = document.querySelectorAll('.modal-backdrop.show');
      backs.forEach(function (b, i) {
        if (i === backs.length - 1) b.classList.add('afd-child-backdrop');
        else {
          b.style.opacity = '0.44';
          b.style.backgroundColor = '#000';
        }
      });
      if (selYear) selYear.focus();
    });

    modalEl.addEventListener('hidden.bs.modal', function () {
      document.body.classList.remove('attendance-child-open');
      document.querySelectorAll('.modal-backdrop.afd-child-backdrop').forEach(function (b) {
        b.classList.remove('afd-child-backdrop');
        b.style.opacity = '';
        b.style.backgroundColor = '';
      });
      var ob = openerBtn;
      openerBtn = null;
      if (ob && typeof ob.focus === 'function') {
        try {
          ob.focus({ preventScroll: true });
        } catch (e) {
          ob.focus();
        }
      }
      if (parentModalSel) {
        var pm = document.querySelector(parentModalSel);
        if (pm && pm.classList.contains('show')) {
          document.body.classList.add('modal-open');
          document.body.style.overflow = 'hidden';
          document.body.style.paddingRight = '';
        }
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.modal-attendance-detail[data-attendance-detail-modal]').forEach(initModal);
  });

  window.AttendanceDetailModalUtils = {
    groupAttendanceByMonth: groupAttendanceByMonth,
    filterRecords: filterRecords,
    normalizeRecord: normalizeRecord,
    recordDate: recordDate,
  };
})();

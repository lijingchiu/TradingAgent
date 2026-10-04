'use strict';

/* A read-only view of the published snapshot. No order endpoint or credentials. */
(() => {
  const $ = id => document.getElementById(id);
  const state = { snapshot: null, chartMode: 'paper', filter: 'all', loading: false };
  const number = value => value === null || value === undefined || value === '' || typeof value === 'boolean' ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const firstNumber = (...values) => values.map(number).find(value => value !== null) ?? null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const display = value => value === null || value === undefined || value === '' ? '—' : String(value);
  const fmt = (value, places = 2) => number(value) === null ? '—' : new Intl.NumberFormat('en-US', { minimumFractionDigits: places, maximumFractionDigits: places }).format(Number(value));
  const money = (value, signed = false) => number(value) === null ? '—' : `${signed && Number(value) > 0 ? '+' : Number(value) < 0 ? '−' : ''}$${fmt(Math.abs(Number(value)))}`;
  const percent = (value, fraction = false, places = 2) => number(value) === null ? '—' : `${fmt(Number(value) * (fraction ? 100 : 1), places)}%`;
  const signedPercent = value => number(value) === null ? '—' : `${Number(value) > 0 ? '+' : ''}${percent(value,false,Number(value) !== 0 && Math.abs(Number(value)) < .01 ? 4 : 2)}`;
  const tone = value => number(value) === null || Number(value) === 0 ? 'neutral' : Number(value) > 0 ? 'positive' : 'negative';
  const timestamp = value => {
    if (!value) return null;
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
  };
  const time = (value, options = {}) => {
    const date = timestamp(value);
    return date ? new Intl.DateTimeFormat('zh-TW', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...options }).format(date).replace(/\//g, '-') : '—';
  };
  const dateLabel = value => timestamp(value) ? new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(timestamp(value)) : '—';
  const text = (id, value) => { $(id).textContent = value; };
  const painted = (id, value, formatted) => { text(id, formatted); $(id).classList.remove('positive', 'negative', 'neutral'); $(id).classList.add(tone(value)); };
  const safeURL = value => {
    try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
  };
  const list = value => Array.isArray(value) ? value : [];
  const translated = value => {
    const messages = {
      'No candidate passed development and validation requirements': '沒有候選策略同時通過研發及驗證門檻',
      'Final holdout has fewer than 30 naturally closed trades': '最終留出資料少於 30 筆自然平倉交易',
      'Final net winning-trade proportion is below 50%': '最終留出資料的扣成本勝率低於 50%',
      'Final profit is not positive after modeled costs': '最終留出資料扣除模型成本後，淨損益未為正',
      'Final test contains a risk-limit breach': '最終留出測試發生風險額度違規',
      'Past profitability does not establish future profitability': '歷史獲利不代表未來獲利。',
      'Public FX observations are not independently authenticated executable quotes': '公開外匯資料為指示性報價，並非經獨立核驗的券商可成交價。',
      'OHLC execution conservatively gives stop priority when both thresholds touch': '同一根 K 棒同時觸碰停損與目標時，回測優先以停損出場。',
      'Win-rate confidence intervals ignore serial trade dependence': '勝率 95% 區間未考慮交易序列的相關性。',
      'Very small fully funded positions limit profits and absolute losses': '小額、全額付款的外幣部位使獲利及虧損金額較低。',
      'Realized and close-mark account drawdown can accumulate across separate trades': '累計損益及收盤估值的帳戶回撤可跨多筆交易累積。',
      'Old mirror timezone and executable-price provenance are unknown; four-hour alignment is exploratory': '歷史鏡像的原始時區及成交價來源未確認；4 小時對齊僅用於探索。'
    };
    const line = String(value ?? '');
    if (messages[line]) return messages[line];
    const trials = line.match(/^Validation was reused to develop cost-aware families; all (\d+) trials (?:must be|are) disclosed$/);
    if (trials) return `驗證資料曾重複用於研發成本敏感策略；已揭露全部 ${trials[1]} 組試驗。`;
    if (line.includes('；')) return line.split('；').map(translated).join('；');
    return line;
  };

  function setStatus(snapshot, failure = null) {
    const status = snapshot?.status || {};
    const market = snapshot?.market || {};
    const code = String(status.code || '').toLowerCase();
    const stale = market.stale === true || /stale|error|unavailable|failed/.test(code);
    const active = /active|monitor|ready|running|paper|market_closed|waiting_signal/.test(code) && snapshot?.validation?.passed === true;
    const banner = $('status-banner');
    banner.className = `status-banner ${failure || /error|failed|risk_halted/.test(code) ? 'error' : stale || !active ? 'waiting' : ''}`;
    text('status-label', failure ? '監控快照連線中斷' : display(status.label || (snapshot?.validation?.passed === true ? stale ? '行情過期暫停' : '模擬監控中' : '等待回測驗證')));
    text('status-reason', failure ? `本次讀取失敗；${snapshot ? '以下保留上次快照，並非目前即時狀態。' : '目前沒有可用快照。'} ${failure}` : translated(status.reason) || '等待執行狀態說明。');
    text('updated-at', time(snapshot?.generated_at));
    text('connection-state', failure ? '快照讀取失敗' : '已讀取快照');
    $('connection-state').classList.toggle('negative', Boolean(failure));
  }

  function render(snapshot) {
    const account = snapshot.account || {};
    const validation = snapshot.validation || {};
    const metrics = validation.final_metrics || {};
    const risk = snapshot.risk || {};
    const market = snapshot.market || {};
    const strategy = snapshot.strategy || {};
    const status = snapshot.status || {};
    const realized = number(account.realized_pnl), unrealized = number(account.unrealized_pnl);
    const pnl = realized !== null && unrealized !== null ? realized + unrealized : null;
    const initial = number(account.initial_equity), equity = number(account.equity);
    const netReturn = initial !== null && initial > 0 && equity !== null ? (equity / initial - 1) * 100 : null;
    text('equity-value', money(equity));
    text('initial-equity', money(initial));
    painted('forward-pnl', pnl, money(pnl, true));
    painted('forward-return', netReturn, netReturn === null ? '尚未取得帳戶資料' : `${signedPercent(netReturn)} 自啟動起`);
    text('forward-trades', `${fmt(account.trade_count, 0)} 筆已平倉`);
    const worst = firstNumber(risk.worst_case_loss, account.position?.worst_case_loss, account.position?.plan?.worst_case_loss,account.position === null ? 0 : null);
    const budget = firstNumber(risk.risk_budget, account.position?.risk_budget, account.position?.plan?.risk_budget, equity === null ? null : equity * .01);
    text('worst-loss', money(worst));
    text('risk-budget', money(budget));
    text('risk-utilization', worst !== null && equity !== null && equity > 0 ? `${percent(worst / equity, true)} 帳戶淨值` : '尚未取得部位資料');
    $('risk-meter-fill').style.width = worst !== null && budget !== null && budget > 0 ? `${Math.min(100, Math.max(0, worst / budget * 100))}%` : '0%';
    $('risk-meter-fill').style.background = worst !== null && budget !== null && worst > budget ? 'var(--red)' : 'var(--mint)';
    text('holdout-win-rate', percent(metrics.win_rate, true, 1));
    const holdoutCount = firstNumber(metrics.trade_count,metrics.eligible_trades);
    text('holdout-sample', holdoutCount === null ? '尚未取得驗證結果' : `${fmt(holdoutCount, 0)} 筆自然出場`);
    const result = validation.passed === true ? 'passed' : validation.passed === false ? 'failed' : 'pending';
    $('validation-badge').className = `result-badge ${result}`;
    text('validation-badge', result === 'passed' ? '通過門檻' : result === 'failed' ? '未通過' : '待驗證');
    text('strategy-symbol', strategy.symbol || market.symbol || '—');
    text('strategy-timeframe', timeframe(strategy.timeframe));
    text('strategy-name', strategy.name || '—');
    text('market-mid', fmt(market.mid, 5));
    text('market-time', time(market.quote_time));
    text('market-state', market.stale === true ? '過期' : market.stale === false && number(market.mid) !== null ? '可用報價' : '待更新');
    $('market-state').classList.toggle('stale', market.stale === true);
    text('next-session', time(status.next_session_at));
    text('last-success', time(status.last_success_at));
    text('cash-value', money(account.cash));
    const holding = firstNumber(strategy.config?.max_days, risk.max_holding_days);
    text('max-holding', holding === null ? '—' : `最多 ${fmt(holding, 0)} 個日曆日`);
    const features = strategy.config || {};
    const description = number(features.rsi_entry) !== null && number(features.ema_period) !== null ? `${features.trend_filter === 'below' ? '趨勢下方' : features.trend_filter === 'none' ? '無趨勢限制，' : '趨勢上方'} RSI(${display(features.rsi_period)}) ≤ ${fmt(features.rsi_entry, 0)} 時觀察入場；使用 EMA(${fmt(features.ema_period, 0)}) 趨勢濾網。完成 K 棒後判斷，下一根開盤模擬成交。` : '回測與前向模擬使用同一份訊號及成交邏輯。';
    text('strategy-note', description);
    setStatus(snapshot);
    renderPosition(snapshot);
    renderIntradayResearch(snapshot);
    renderValidation(snapshot);
    renderTrades(snapshot);
    renderSources(snapshot);
    renderChart(snapshot);
  }

  function timeframe(value) {
    const name = String(value || '').toLowerCase();
    const hourMatch = name.match(/^(\d+)h$/);
    if (hourMatch) return `${Number(hourMatch[1])} 小時線 · 下一時段成交`;
    return ({'1d': '日線 · 下一時段成交', 'd1': '日線 · 下一時段成交', 'daily': '日線 · 下一時段成交', '1h': '小時線 · 下一時段成交', 'h1': '小時線 · 下一時段成交'})[name] || (value ? `${display(value)} · 固定參數` : '等待策略資料');
  }

  function renderPosition(snapshot) {
    const account = snapshot.account || {};
    const position = account.position;
    if (position === null) {
      text('position-state', '空手');
      $('position-content').innerHTML = '<div class="inline-empty"><span class="empty-position-icon" aria-hidden="true">◎</span><div><strong>目前沒有持倉</strong><p>等待有效訊號與可用行情。通過驗證後才允許模擬入場。</p></div></div>';
      return;
    }
    if (!position || typeof position !== 'object') {
      text('position-state', '待更新');
      $('position-content').innerHTML = '<div class="inline-empty"><span class="empty-position-icon" aria-hidden="true">◎</span><div><strong>尚未取得部位資訊</strong><p>部位、停損及出場目標將由實際快照更新。</p></div></div>';
      return;
    }
    text('position-state', '持有外幣 · 多單');
    const plan = position.plan || position;
    const rows = [
      ['數量 · 外幣單位', fmt(firstNumber(position.units, plan.units), 0), ''],
      ['進場價格', fmt(firstNumber(position.entry_price, position.entry_fill, plan.entry_fill), 5), ''],
      ['停損中間價', fmt(firstNumber(position.stop_price, plan.stop_price), 5), ''],
      ['目標中間價', fmt(position.target_price, 5), ''],
      ['可清算未實現損益', money(account.unrealized_pnl, true), tone(account.unrealized_pnl)],
      ['進場時間 · 台北', time(position.entry_time), 'small']
    ];
    const worst = firstNumber(position.worst_case_loss, plan.worst_case_loss);
    const entryEquity = firstNumber(position.entry_equity, plan.entry_equity);
    const maxDays = firstNumber(position.max_days, plan.max_days);
    const entryDate = timestamp(position.entry_time);
    const expiry = entryDate && maxDays !== null ? new Date(entryDate.getTime() + maxDays * 86400000).toISOString() : null;
    $('position-content').innerHTML = `<dl class="position-grid">${rows.map(([label,value,cls]) => `<div class="position-stat"><dt>${escape(label)}</dt><dd class="${escape(cls)}">${escape(value)}</dd></div>`).join('')}</dl><div class="position-extra"><span>最壞損失額 <strong>${escape(money(worst))}</strong></span><span>占進場淨值 <strong>${escape(entryEquity !== null && entryEquity > 0 && worst !== null ? percent(worst / entryEquity, true) : '—')}</strong></span><span>最晚期限 <strong>${escape(time(position.expires_at || expiry))}</strong></span></div>`;
  }

  function hasIntradayResearch(snapshot) {
    const research = snapshot?.intraday_research;
    return Boolean(research && typeof research === 'object' && !Array.isArray(research) && Object.keys(research).length);
  }

  function researchStatus(value) {
    const code = typeof value === 'object' && value ? value.label || value.code || value.status : value;
    const labels = { rejected:'未通過', failed:'未通過', no_edge:'未找到正期望值',
      completed_no_edge:'未找到正期望值', unqualified:'未合格', blocked:'受阻',
      pending:'待完成', pending_ask:'等待 ASK 資料', awaiting_ask:'等待 ASK 資料',
      pending_quotes:'等待完整報價', running:'研究中', researching:'研究中',
      completed:'評估完成', provisional:'暫定結果', qualified:'開發／驗證合格',
      qualified_pre_final:'待最終評估', frozen:'參數已凍結', not_started:'尚未評估' };
    return labels[String(code)] || display(code);
  }

  function researchPeriod(value) {
    if (Array.isArray(value)) return value.map(display).join(' 至 ');
    if (value && typeof value === 'object') return value.start && value.end ? `${value.start} 至 ${value.end}` : JSON.stringify(value);
    return display(value);
  }

  function researchMoney(value, currency) {
    const amount = number(value);
    if (amount === null) return '—';
    const code = typeof currency === 'string' && /^[A-Z]{3}$/.test(currency.toUpperCase()) ? currency.toUpperCase() : null;
    return `${amount > 0 ? '+' : amount < 0 ? '−' : ''}${code ? code + ' ' : ''}${fmt(Math.abs(amount))}${code ? '' : '（幣別未提供）'}`;
  }

  function renderIntradayResearch(snapshot) {
    const available = hasIntradayResearch(snapshot);
    $('intraday-research').hidden = !available;
    $('intraday-nav').hidden = !available;
    const oldTimeframe = String(snapshot.strategy?.timeframe || '');
    const match = oldTimeframe.match(/^(\d+)h$/i);
    const oldScope = match ? `${Number(match[1])} 小時` : oldTimeframe;
    text('validation-title', available ? `既有${oldScope ? ' ' + oldScope : ''}策略・歷史驗證` : '策略驗證');
    text('validation-subtitle', available ? '先前研究結果 · 與本輪 5／15 分鐘研究分開 · 已扣模型成本' : '歷史回測結果 · 已扣除模型交易成本');
    text('holdout-card-label', available ? '既有策略留出勝率' : '最終留出勝率');
    if (!available) return;
    const research = snapshot.intraday_research;
    text('intraday-label', research.label || researchStatus(research.status));
    text('intraday-reason', research.reason || '等待完整研究狀態說明。');
    const status = String(research.status || '').toLowerCase();
    $('intraday-state').className = `intraday-state ${/fail|reject|no_edge|unqualified/.test(status) ? 'failed' : /qualified|frozen|passed/.test(status) ? 'qualified' : 'pending'}`;
    text('intraday-variants', fmt(research.parameter_variant_count,0));
    text('intraday-evaluations', fmt(research.source_evaluation_count,0));
    text('intraday-final-state', research.final_untouched === true ? '尚未評估' : research.final_untouched === false ? '已進行評估' : '待確認');
    text('intraday-selected', research.selected === null ? '未選定' : research.selected?.name || '尚未提供');
    const stages = [['開發','development'],['選擇驗證','validation'],['最終保留','final']];
    $('intraday-periods').innerHTML = stages.map(([label,key]) => `<span><strong>${escape(label)}</strong>${escape(researchPeriod(research.periods?.[key]))}</span>`).join('');
    const supplementCounts = [number(research.diagnostic_evaluation_count) === null ? null : `${fmt(research.diagnostic_evaluation_count,0)} 次額外診斷`,number(research.untuned_control_count) === null ? null : `${fmt(research.untuned_control_count,0)} 組固定基準`].filter(Boolean);
    const countNote = [research.count_note || null,supplementCounts.length ? supplementCounts.join('；') + '另列，不當作已合格策略。' : null].filter(Boolean).join(' ');
    $('intraday-count-note').hidden = !countNote;
    text('intraday-count-note',countNote);
    const families = list(research.families).filter(value => value && typeof value === 'object');
    $('intraday-family-rows').innerHTML = families.length ? families.map(family => {
      const diagnostic = family.diagnostic || {};
      const count = number(diagnostic.trade_count);
      const split = ({development:'開發',validation:'選擇驗證',final:'最終評估',train:'訓練'})[diagnostic.split] || display(diagnostic.split);
      const interval = Array.isArray(family.timeframes) ? family.timeframes.join('／') : display(family.timeframes);
      const familyState = typeof family.status === 'object' ? family.status?.code : String(family.status || '');
      const stateClass = /fail|reject|no_edge|unqualified|未通過|未合格/.test(familyState) ? 'failed' : /qualified|frozen|passed/.test(familyState) ? 'passed' : 'pending';
      const sample = count === null ? '尚無區間診斷' : `${split} · ${fmt(count,0)} 筆`;
      const explanation = diagnostic.explanation ? `<span class="research-cell-note diagnostic-explanation">${escape(diagnostic.explanation)}</span>` : '';
      return `<tr><td>${escape(family.name || '—')}</td><td>${escape(family.symbol || '—')}<span class="research-cell-note">${escape(interval)}</span></td><td>${escape(fmt(family.trials,0))}</td><td><span class="result-badge ${stateClass}">${escape(researchStatus(family.status))}</span></td><td class="research-diagnostic">${escape(sample)}${explanation}</td><td>${escape(count === 0 ? '—' : percent(diagnostic.win_rate,true,1))}</td><td class="${tone(diagnostic.net_profit)}">${escape(researchMoney(diagnostic.net_profit,diagnostic.currency))}</td></tr>`;
    }).join('') : '<tr><td colspan="7" class="table-empty">尚未提供策略家族評估。</td></tr>';
    const sources = research.sources || {};
    const sourceFacts = [['資料供應者',display(sources.provider)],['既有 Dukascopy M5 BID',fmt(sources.bid_m5_bars,0)],['既有 Dukascopy M15 BID',fmt(sources.bid_m15_bars,0)],['價格側／時區',`${display(sources.quote_side)} ／ ${display(sources.time_zone)}`]];
    if (number(sources.fxcm_paired_m5_bars) !== null) sourceFacts.push(['FXCM 雙側 M5 根數',fmt(sources.fxcm_paired_m5_bars,0)]);
    if (number(sources.fxcm_paired_m15_bars) !== null) sourceFacts.push(['FXCM 雙側 M15 根數',fmt(sources.fxcm_paired_m15_bars,0)]);
    if (sources.fxcm_periods) sourceFacts.push(['FXCM 資料區間',display(sources.fxcm_periods)]);
    if (sources.futures_status) sourceFacts.push(['期貨來源及限制',display(sources.futures_status)]);
    $('intraday-source-facts').innerHTML = sourceFacts.map(([label,value]) => `<div><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`).join('');
    text('intraday-ask-status', `ASK 資料狀態：${sources.ask_status ? typeof sources.ask_status === 'string' ? sources.ask_status : JSON.stringify(sources.ask_status) : '尚未提供完整性資訊'}。BID OHLC 與假設價差不足以證明完整可成交的買賣報價。`);
    text('intraday-freeze-note', research.final_untouched === true ? '尚未檢視最終區間的策略績效；先凍結策略、成本與資料來源，再進行最終評估。' : research.final_untouched === false ? '最終區間已進行策略評估；此研究面板不改變獨立的模擬入場門檻。' : '最終評估狀態尚未確認；此研究面板不改變獨立的模擬入場門檻。');
    let reportURL = null;
    if (typeof research.report_url === 'string') {
      try {
        const url = new URL(research.report_url,window.location.href);
        if (url.protocol === 'https:' || url.origin === window.location.origin && ['http:','https:'].includes(url.protocol)) reportURL = url.href;
      } catch { /* Invalid links stay hidden. */ }
    }
    $('intraday-report-link').hidden = !reportURL;
    if (reportURL) $('intraday-report-link').href = reportURL;
    else $('intraday-report-link').removeAttribute('href');
    const review = research.stop_review;
    if ($('stop-review')) {
      $('stop-review').hidden = !review?.reference_case;
      if (review?.reference_case) {
        const reference = review.reference_case;
        text('stop-review-scope',`${display(reference.symbol)} · ${fmt(reference.minutes,0)} 分鐘 · ${display(reference.period)} · 研究資金 ${money(reference.initial_equity_usd)}；與前向帳戶分開。下表為 2018–2021 選擇驗證。`);
        text('stop-review-count',fmt(reference.stopped_trades,0));
        text('stop-review-loss',`${fmt(reference.mean_stopped_net_pips)} 點`);
        text('stop-review-win',`${fmt(reference.mean_winning_net_pips)} 點`);
        text('stop-review-duration',`${fmt(Number(reference.winning_median_holding_bars)*Number(reference.minutes),0)} 分鐘`);
        text('stop-review-summary',review.summary);
        text('stop-review-feature-note',review.entry_feature_note);
        $('stop-review-rows').innerHTML = list(review.validation_comparisons).map(row => `<tr><td>${escape(row.label)}</td><td>${escape(fmt(row.natural_trades,0))}</td><td>${escape(percent(row.win_rate,true,2))}</td><td class="${tone(row.net_profit_usd)}">${escape(researchMoney(row.net_profit_usd,'USD'))}</td><td class="${tone(row.mean_net_pnl_usd)}">${escape(fmt(row.mean_net_pnl_usd,4))}</td></tr>`).join('');
        const reviewURL = safeURL(review.report_url);
        $('stop-review-link').hidden = !reviewURL;
        if (reviewURL) $('stop-review-link').href = reviewURL;
        else $('stop-review-link').removeAttribute('href');
      }
    }
  }

  function renderValidation(snapshot) {
    const validation = snapshot.validation || {};
    text('candidate-count', `候選策略 ${fmt(validation.candidate_count, 0)}`);
    const passed = validation.passed;
    const summary = $('validation-summary');
    summary.className = `validation-summary ${passed === true ? '' : passed === false ? 'failed' : 'pending'}`;
    const fullMessage = passed === true ? '歷史驗證符合門檻：最終留出勝率至少 50%，扣除模型成本後淨損益為正。前向模擬績效將另行累積。' : passed === false ? translated(validation.reason) || '驗證未通過設定門檻。系統不新增模擬部位，仍繼續更新監控資料。' : '尚未取得完整回測報告。模擬入場需等待驗證。';
    summary.innerHTML = `<span class="validation-symbol" aria-hidden="true">${passed === true ? '✓' : passed === false ? '×' : '○'}</span><span>${escape(fullMessage)}</span>`;
    const phases = [ ['訓練', 'train_metrics', '設定候選參數'], ['驗證', 'validation_metrics', '選定同一組策略'], ['最終留出', 'final_metrics', '凍結參數後評估'], ['成本壓力測試', 'stress_metrics', '較高成本假設'] ];
    const hasData = phases.some(([,key]) => validation[key] && typeof validation[key] === 'object');
    $('validation-rows').innerHTML = hasData ? phases.map(([label,key,desc]) => {
      const m = validation[key] || {};
      const period = validation.periods?.[key] || validation.periods?.[key.replace('_metrics','').replace('train','development')] || m.period || m.date_range || (m.first_bar && m.last_bar ? {start:m.first_bar,end:m.last_bar} : null);
      let periodText = desc;
      if (typeof period === 'string') periodText = period;
      else if (period?.start && period?.end) periodText = `${dateLabel(period.start)} 至 ${dateLabel(period.end)}`;
      const count = firstNumber(m.trade_count,m.eligible_trades);
      const wr = count === 0 ? '—' : percent(m.win_rate, true, 1);
      const factor = ['infinity','inf'].includes(String(m.profit_factor).toLowerCase()) ? '∞' : fmt(m.profit_factor);
      const intervalValues = m.confidence_interval || m.win_rate_wilson_95;
      const interval = Array.isArray(intervalValues) && intervalValues.length === 2 && intervalValues.every(value => number(value) !== null) ? `95% 區間 ${percent(intervalValues[0],true,1)}–${percent(intervalValues[1],true,1)}` : null;
      const winCell = `${escape(wr)}${interval && count > 0 ? `<span class="confidence-interval">${escape(interval)}</span>` : ''}`;
      const drawdown = firstNumber(m.max_drawdown_pct,number(m.max_account_drawdown_close_marks) === null ? null : Number(m.max_account_drawdown_close_marks)*100);
      const maxAdverse = firstNumber(m.max_trade_loss_pct,number(m.max_trade_adverse_equity_fraction) === null ? null : Number(m.max_trade_adverse_equity_fraction)*100);
      return `<tr${key === 'final_metrics' ? ' class="final-phase"' : ''}><td class="phase-cell"><strong>${escape(label)}</strong><span>${escape(periodText)}</span></td><td>${escape(fmt(count, 0))}</td><td>${winCell}</td><td class="${tone(m.net_profit)}">${escape(money(m.net_profit, true))}</td><td>${escape(factor)}</td><td>${escape(percent(drawdown,false,3))}</td><td>${escape(percent(maxAdverse,false,4))}</td></tr>`;
    }).join('') : '<tr><td colspan="7" class="table-empty">尚未取得回測資料</td></tr>';
    const warnings = list(validation.warnings).map(value => typeof value === 'string' ? translated(value) : JSON.stringify(value));
    $('validation-warnings').hidden = warnings.length === 0;
    $('validation-warnings').innerHTML = warnings.map(value => `<p>${escape(value)}</p>`).join('');
  }

  function reason(value) {
    return ({ stop: '停損', stop_loss: '停損', gap_stop: '跳空停損', target: '停利目標', take_profit: '停利目標', max_days: '持有期限', timeout: '持有期限', expiry: '持有期限', time_exit: '持有期限', sample_end: '回測區間結束', end_of_data: '資料區間結束', end_of_backtest: '回測區間結束', manual_close: '強制平倉', stale_exit: '資料異常退出' })[String(value)] || display(value);
  }

  function renderTrades(snapshot) {
    if (!Array.isArray(snapshot.trades)) {
      $('trade-rows').innerHTML = '<tr><td colspan="7" class="table-empty">尚未取得前向模擬交易資料</td></tr>';
      text('trade-count-label', '— 筆交易');
      return;
    }
    const all = snapshot.trades.filter(trade => trade && typeof trade === 'object' && !/backtest|train|validation|final|stress/i.test(String(trade.segment || trade.mode || '')));
    const filtered = all.filter(trade => state.filter === 'all' || state.filter === 'profit' && number(trade.net_pnl) > 0 || state.filter === 'loss' && number(trade.net_pnl) !== null && number(trade.net_pnl) < 0 || state.filter === 'flat' && number(trade.net_pnl) === 0).sort((a,b) => (timestamp(b.exit_time)?.getTime() || 0) - (timestamp(a.exit_time)?.getTime() || 0));
    text('trade-count-label', state.filter === 'all' ? `${fmt(all.length, 0)} 筆前向模擬交易` : `顯示 ${fmt(filtered.length, 0)} / ${fmt(all.length, 0)} 筆前向模擬交易`);
    if (!filtered.length) {
      const message = all.length ? '此條件下沒有交易紀錄' : '尚無已平倉的前向模擬單；回測獲利不會列為實際模擬交易。';
      $('trade-rows').innerHTML = `<tr><td colspan="7" class="table-empty">${escape(message)}</td></tr>`;
      return;
    }
    $('trade-rows').innerHTML = filtered.map(trade => {
      const fee = firstNumber(trade.total_fees, trade.fees, number(trade.entry_commission) !== null && number(trade.exit_commission) !== null && number(trade.carry) !== null ? Number(trade.entry_commission) + Number(trade.exit_commission) + Number(trade.carry) : null);
      const adverse = number(trade.mae_pct) !== null ? Number(trade.mae_pct) : number(trade.max_adverse_excursion) !== null && number(trade.entry_equity) > 0 ? Number(trade.max_adverse_excursion) / Number(trade.entry_equity) * 100 : null;
      return `<tr><td class="trade-time">${escape(time(trade.entry_time))}<span>${escape(time(trade.exit_time))}</span></td><td><span class="trade-direction">多</span>${escape(fmt(trade.units,0))}</td><td class="trade-price">${escape(fmt(firstNumber(trade.entry_price, trade.entry_fill),5))}<span>${escape(fmt(firstNumber(trade.exit_price, trade.exit_fill),5))}</span></td><td>${escape(money(fee))}</td><td class="${tone(trade.net_pnl)}">${escape(money(trade.net_pnl,true))}</td><td${trade.risk_breach === true ? ' class="negative"' : ''}>${escape(percent(adverse,false,4))}</td><td>${escape(reason(trade.reason))}</td></tr>`;
    }).join('');
  }

  function renderSources(snapshot) {
    const costs = snapshot.costs || snapshot.strategy?.config?.costs || snapshot.source_metadata?.cost_model || {};
    const costRows = [
      ['完整買賣價差', number(costs.spread_pips) === null ? '—' : `${fmt(costs.spread_pips, 1)} pips`],
      ['每側滑價', number(costs.slippage_pips) === null ? '—' : `${fmt(costs.slippage_pips, 1)} pips`],
      ['每側佣金', number(costs.commission_bps) === null ? '—' : `${fmt(costs.commission_bps, 2)} bps`],
      ['每側最低佣金', money(costs.minimum_commission)],
      ['持有成本 · 每千美元每日', money(costs.carry_per_1000_per_day)]
    ];
    $('cost-facts').innerHTML = costRows.map(([label,value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('');
    const metadata = snapshot.source_metadata || {};
    const entries = Array.isArray(metadata) ? metadata : [metadata];
    const sourceName = typeof metadata.source === 'string' ? metadata.source : typeof metadata.provider === 'string' ? metadata.provider : snapshot.market?.source;
    const blocks = [];
    if (Array.isArray(metadata)) {
      entries.forEach(entry => {
        if (!entry || typeof entry !== 'object') return;
        blocks.push(`<p class="source-heading">${escape(entry.source || entry.name || '資料來源')}</p>`);
        if (entry.date_range) blocks.push(`<p>${escape(typeof entry.date_range === 'string' ? entry.date_range : JSON.stringify(entry.date_range))}</p>`);
        if (entry.data_quality) blocks.push(`<p>${escape(entry.data_quality)}</p>`);
      });
    }
    if (!Array.isArray(metadata) && sourceName) blocks.push(`<p class="source-heading">${escape(sourceName)}</p>`);
    if (metadata.description) blocks.push(`<p>${escape(metadata.description)}</p>`);
    if (metadata.date_range) blocks.push(`<p>資料區間：${escape(typeof metadata.date_range === 'string' ? metadata.date_range : JSON.stringify(metadata.date_range))}</p>`);
    const urls = new Map();
    const addURL = (value,label) => { const url = safeURL(value); if (url && !urls.has(url)) urls.set(url,label || new URL(url).hostname); };
    addURL(snapshot.market?.source_url,'最新報價來源');
    entries.forEach(entry => { if (!entry || typeof entry !== 'object') return; addURL(entry.url,entry.name || entry.source); addURL(entry.source_url,entry.name || entry.source); });
    list(metadata.sources).forEach(source => typeof source === 'string' ? addURL(source) : addURL(source?.url,source?.name || source?.source));
    if (!blocks.length) blocks.push('<p>資料來源、下載時間與驗證方式見下方中繼資料。</p>');
    if (urls.size) blocks.push(`<p style="margin-top:9px">${Array.from(urls,([url,label]) => `<a class="source-link" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label)} <span aria-hidden="true">↗</span></a>`).join('<br>')}</p>`);
    if (metadata.limitations) blocks.push(`<p style="margin-top:9px">${escape(Array.isArray(metadata.limitations) ? metadata.limitations.join('；') : metadata.limitations)}</p>`);
    $('source-content').innerHTML = blocks.join('');
    text('source-json', JSON.stringify(metadata,null,2));
    const executionNotes = list(snapshot.execution_notes);
    $('execution-notes').hidden = executionNotes.length === 0;
    $('execution-notes').innerHTML = executionNotes.length ? `<p class="source-heading">排程與成交模型</p>${executionNotes.map(note => `<p>${escape(note)}</p>`).join('')}` : '';
  }

  function curveRows(snapshot) {
    const explicit = state.chartMode === 'backtest' ? snapshot.backtest_equity_curve || snapshot.validation?.equity_curve : snapshot.account?.equity_curve;
    const rows = Array.isArray(explicit) ? explicit : list(snapshot.equity_curve).filter(row => {
      const segment = String(row.segment || '').toLowerCase();
      return state.chartMode === 'paper' ? !segment || /paper|forward|live|simulation/.test(segment) : /backtest|train|valid|final|holdout|stress/.test(segment);
    });
    return rows.filter(row => number(row?.equity) !== null && timestamp(row?.timestamp || row?.time)).map(row => ({ timestamp: row.timestamp || row.time, equity: Number(row.equity), segment: String(row.segment || '') })).sort((a,b) => timestamp(a.timestamp) - timestamp(b.timestamp));
  }

  function renderChart(snapshot) {
    const backtest = state.chartMode === 'backtest';
    text('equity-chart-title', backtest ? hasIntradayResearch(snapshot) ? '既有策略歷史回測淨值' : '歷史回測淨值走勢' : '帳戶淨值走勢');
    text('chart-subtitle', backtest ? `${hasIntradayResearch(snapshot) ? '先前研究策略' : '歷史策略模擬'} · USD · 各區間分開連線` : '前向模擬紀錄 · USD');
    text('chart-series-label', backtest ? '回測模型淨值' : '模擬帳戶淨值');
    const rows = curveRows(snapshot);
    const chart = $('equity-chart');
    if (!rows.length) {
      text('chart-equity', backtest ? '—' : money(snapshot.account?.equity));
      text('chart-change', '尚無時間序列');
      $('chart-change').className = 'chart-change';
      text('chart-period', '期間 —');
      chart.setAttribute('aria-label', backtest ? '沒有歷史回測淨值序列' : '没有前向模擬淨值序列');
      chart.innerHTML = `<div class="empty-state"><div class="empty-chart-icon" aria-hidden="true">⌁</div><strong>${backtest ? '尚無回測淨值序列' : '等待前向模擬紀錄'}</strong><p>${backtest ? '回測摘要可於下方策略驗證查看；不以未提供的資料補線。' : '啟動後的模擬淨值將在此累積，歷史回測獲利不列入。'}</p></div>`;
      return;
    }
    const first = rows[0], last = rows[rows.length - 1];
    const initial = backtest ? first.equity : firstNumber(snapshot.account?.initial_equity,first.equity);
    const delta = initial > 0 ? (last.equity / initial - 1) * 100 : null;
    text('chart-equity',money(last.equity));
    painted('chart-change',delta,delta === null ? '—' : `${signedPercent(delta)} 區間變化`);
    text('chart-period',`${dateLabel(first.timestamp)} 至 ${dateLabel(last.timestamp)}`);
    chart.setAttribute('aria-label',`${backtest ? '歷史回測' : '前向模擬'}淨值，${rows.length} 筆資料，${dateLabel(first.timestamp)} 至 ${dateLabel(last.timestamp)}，起始 ${money(first.equity)}，最新 ${money(last.equity)}。縱軸依數據縮放。`);
    const width = Math.max(300,chart.clientWidth - (window.innerWidth < 540 ? 18 : 30)), height = Math.max(210,chart.clientHeight - 17), left = 70, right = 15, top = 12, bottom = 30;
    const plotW = width - left - right, plotH = height - top - bottom;
    const values = rows.map(row => row.equity).concat(initial);
    let lo = Math.min(...values), hi = Math.max(...values);
    const padding = hi === lo ? Math.max(Math.abs(lo) * .0002,1) : (hi-lo) * .16;
    lo -= padding; hi += padding;
    const t0 = timestamp(first.timestamp).getTime(), t1 = timestamp(last.timestamp).getTime();
    const x = row => t1 === t0 ? left + plotW / 2 : left + (timestamp(row.timestamp).getTime()-t0) / (t1-t0) * plotW;
    const y = value => top + plotH - (value-lo) / (hi-lo) * plotH;
    const precision = hi-lo < 5 ? 2 : hi-lo < 50 ? 1 : 0;
    const grid = Array.from({length:5},(_,i) => { const value = lo + (hi-lo) * i / 4; return `<line class="grid-line" x1="${left}" y1="${y(value).toFixed(2)}" x2="${width-right}" y2="${y(value).toFixed(2)}"/><text x="${left-12}" y="${(y(value)+3).toFixed(2)}" text-anchor="end">${escape(fmt(value,precision))}</text>`; }).join('');
    const segments = [];
    for (const row of rows) {
      const lastSegment = segments[segments.length-1];
      if (!lastSegment || lastSegment.key !== row.segment) segments.push({key:row.segment,rows:[row]});
      else lastSegment.rows.push(row);
    }
    const lines = segments.map((segment,i) => {
      const points = segment.rows.map(row => `${x(row).toFixed(2)},${y(row.equity).toFixed(2)}`);
      const firstRow = segment.rows[0], lastRow = segment.rows[segment.rows.length-1];
      const area = `${x(firstRow).toFixed(2)},${(top+plotH).toFixed(2)} ${points.join(' ')} ${x(lastRow).toFixed(2)},${(top+plotH).toFixed(2)}`;
      return `<polygon points="${area}" fill="url(#equity-fill)"/><polyline class="curve-line" points="${points.join(' ')}"/>${segment.rows.length===1 ? `<circle class="curve-dot" cx="${x(firstRow).toFixed(2)}" cy="${y(firstRow.equity).toFixed(2)}" r="4"><title>${escape(time(firstRow.timestamp))} · ${escape(money(firstRow.equity))}</title></circle>` : ''}`;
    }).join('');
    const dates = t0 === t1 ? [{date:first.timestamp,x:x(first),anchor:'middle'}] : [{date:first.timestamp,x:left,anchor:'start'},{date:new Date(t0+(t1-t0)/2).toISOString(),x:left+plotW/2,anchor:'middle'},{date:last.timestamp,x:width-right,anchor:'end'}];
    const tickLabel = value => t1-t0 < 86400000 ? new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',...(t1-t0 < 60000 ? {second:'2-digit'} : {}),hourCycle:'h23'}).format(timestamp(value)) : dateLabel(value);
    const ticks = dates.map(item => `<text x="${item.x.toFixed(2)}" y="${height-7}" text-anchor="${item.anchor}">${escape(tickLabel(item.date))}</text>`).join('');
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true" preserveAspectRatio="none"><defs><linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#75e3bb" stop-opacity=".16"/><stop offset="100%" stop-color="#75e3bb" stop-opacity="0"/></linearGradient></defs>${grid}<line class="baseline" x1="${left}" y1="${y(initial).toFixed(2)}" x2="${width-right}" y2="${y(initial).toFixed(2)}"/>${lines}<circle class="curve-dot" cx="${x(last).toFixed(2)}" cy="${y(last.equity).toFixed(2)}" r="4"><title>${escape(time(last.timestamp))} · ${escape(money(last.equity))}</title></circle>${ticks}</svg>`;
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    $('refresh-button').disabled = true;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(),15000);
      let response;
      try { response = await fetch(`./snapshot.json?t=${Date.now()}`, { cache: 'no-store', credentials: 'omit', signal: controller.signal }); }
      finally { clearTimeout(timeout); }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const snapshot = await response.json();
      if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot) || snapshot.mode !== 'paper') throw new Error('快照格式不符模擬交易監控格式');
      state.snapshot = snapshot;
      render(snapshot);
    } catch (error) {
      setStatus(state.snapshot,error.name === 'AbortError' ? '讀取逾時。' : '請確認發布的 snapshot.json 與排程執行狀態。');
      if (!state.snapshot) { text('trade-count-label','尚無可用快照'); }
    } finally {
      state.loading = false;
      $('refresh-button').disabled = false;
    }
  }
  $('refresh-button').addEventListener('click',refresh);
  $('trade-filter').addEventListener('change',event => { state.filter = event.target.value; if (state.snapshot) renderTrades(state.snapshot); });
  document.querySelectorAll('[data-chart-mode]').forEach(button => button.addEventListener('click',() => {
    state.chartMode = button.dataset.chartMode;
    document.querySelectorAll('[data-chart-mode]').forEach(item => { const selected = item === button; item.classList.toggle('selected',selected); item.setAttribute('aria-selected',String(selected)); });
    if (state.snapshot) renderChart(state.snapshot);
  }));
  document.querySelector('[role="tablist"]').addEventListener('keydown',event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[data-chart-mode]')];
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[index].focus(); tabs[index].click();
  });
  document.querySelectorAll('.nav-item').forEach(link => link.addEventListener('click',() => {
    document.querySelector('[role="tablist"]').addEventListener('keydown',event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[data-chart-mode]')];
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[index].focus(); tabs[index].click();
  });
  document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active',item === link));
    document.querySelectorAll('.nav-dot').forEach(dot => dot.remove());
    const dot = document.createElement('span'); dot.className = 'nav-dot'; link.append(dot);
  }));
  let resizeTimer;
  window.addEventListener('resize',() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (state.snapshot) renderChart(state.snapshot); },120); });
  const clock = () => text('local-clock',time(new Date().toISOString(),{second:'2-digit'}));
  clock(); setInterval(clock,1000);
  refresh(); setInterval(refresh,60000);
})();

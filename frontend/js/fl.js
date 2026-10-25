import {watchTraining, phases, terminal} from './training-stream.js';
const $ = id => document.getElementById(id);
const form = $('experiment-form'), fields = form.elements;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count = value => Number(value || 0).toLocaleString('vi-VN');
const num = (value,d=3) => value == null ? '—' : Number(value).toFixed(d);
let poolRevision = 0, regionInfo = null, poolPending = false, acceptedPoolQuery = null, trainingTarget='fl_rtt';
let datasets = [], pool = [], busy = false, sizingTimer, previewToken = 0, loadToken = 0, watched = [], fallbackTimer, detailTimer, detailBusy = false;
let liveId = null, lastRound = -1, comparisonId = null, launching = false, viewGeneration = 0;
const runStates=new Map();
function renderComparison(){const box=$('comparison-overview');box.hidden=!comparisonId;box.innerHTML=comparisonId?[...runStates.values()].map(run=>`<div><strong>${esc(run.algorithm)}</strong><span>${esc(run.status)} · ${run.completed_rounds}/${run.target_rounds} vòng</span></div>`).join(''):'';}
const integerFields = ['scenario_id','rounds','client_count','local_epochs','batch_size','seed','samples_per_client','online_steps','timeout_ms'];
function payload() {
    const data = {};
    [...integerFields,'learning_rate','dropout_probability'].forEach(key => data[key] = Number(fields[key].value));
    ['task','algorithm','partition','network_profile','pool_mode'].forEach(key => data[key] = fields[key].value);
    if (data.task === 'network_delay' && fields.dataset_id.value) data.dataset_id = Number(fields.dataset_id.value);
    data.region_radius_km=Number(fields.region_radius_km.value);
    for(const key of ['region_lat','region_lng']) if(fields[key].value.trim()!=='')data[key]=Number(fields[key].value);
    return data;
}
async function api(url, options) {
    const response = await fetch(url,options), result = await response.json();
    if (!response.ok || result.status !== 'success') {
        const errors = Array.isArray(result.detail) ? result.detail.map(item => `${item.loc.at(-1)}: ${item.msg}`).join('; ') : result.detail || result.message;
        throw new Error(errors || `HTTP ${response.status}`);
    }
    return result.data;
}
function message(text,error=false) { $('message').textContent=text; $('message').classList.toggle('error',error); }
function setBusy(value) { busy=value; const unavailable=value || poolPending || acceptedPoolQuery!==poolQuery(); $('start-button').disabled=unavailable; $('compare-button').disabled=unavailable || fields.algorithm.value==='Centralized'; }
function clearErrors() {
    form.querySelectorAll('.field-error').forEach(node => node.remove());
    form.querySelectorAll('[aria-invalid]').forEach(node => {node.removeAttribute('aria-invalid');node.removeAttribute('aria-describedby');});
    [...form.elements].forEach(node => node.setCustomValidity?.(''));
    $('form-errors').hidden=true;
}
function fieldError(key,text) {
    const field=fields[key]; field.setAttribute('aria-invalid','true'); field.setCustomValidity(text);
    const error=document.createElement('span'); error.className='field-error'; error.id=`error-${key}`; error.textContent=text;
    field.setAttribute('aria-describedby',error.id); field.closest('label').append(error);
}
function validate(showSummary=false) {
    clearErrors(); const data=payload(), errors=[];
    for (const field of [...form.elements].filter(node => node.willValidate)) {
        if (!field.checkValidity()) { const text=field.validationMessage; fieldError(field.name,text); errors.push(text); }
    }
    const fail=(key,text) => { if (!fields[key].hasAttribute('aria-invalid')) {fieldError(key,text);errors.push(text);} };
    integerFields.forEach(key => { if (!fields[key].disabled && (!Number.isSafeInteger(data[key]) || (key !== 'seed' && data[key]<1))) fail(key,'Nhập số nguyên hợp lệ.'); });
    if ((data.region_lat==null)!==(data.region_lng==null)) fail('region_lat','Nhập cả vĩ độ và kinh độ, hoặc để trống cả hai.');
    if (!(data.learning_rate>0) || !Number.isFinite(data.learning_rate)) fail('learning_rate','Learning rate phải là số dương hữu hạn.');
    if (data.algorithm !== 'Centralized' && data.client_count>pool.length) fail('client_count',`Pool có ${pool.length} client ACTIVE hợp lệ.`);
    if (data.task==='network_delay' && !data.dataset_id && data.online_steps<data.rounds) fail('online_steps',`Cần ít nhất ${data.rounds} online ticks để chạy ${data.rounds} vòng.`);
    if (showSummary && errors.length) {
        $('form-errors').textContent=`Cần kiểm tra ${errors.length} thông số được đánh dấu. ${errors[0]}`; $('form-errors').hidden=false;
        const first=form.querySelector('[aria-invalid=true]'); first?.closest('details')?.setAttribute('open',''); first?.focus();
    }
    return !errors.length;
}
function applyDataset() {
    const dataset=datasets.find(row => row.id===Number(fields.dataset_id.value));
    ['seed','partition','network_profile','samples_per_client','online_steps'].forEach(key => {
        fields[key].disabled=Boolean(dataset);
        if (dataset && dataset[key] != null) fields[key].value=dataset[key];
    });
    $('dataset-hint').textContent=dataset ? `Snapshot #${dataset.id} được giữ nguyên. Các trường dữ liệu đã khóa theo metadata.` : 'Dataset mới dùng các client ACTIVE thuộc phạm vi đã chọn.';
}
function updateTask() {
    const network=fields.task.value==='network_delay';
    ['dataset-field','samples-field','online-field'].forEach(id => $(id).hidden=!network);
    ['samples_per_client','online_steps'].forEach(key => fields[key].disabled=!network);
    const predictive=[...fields.algorithm.options].find(option => option.value==='Predictive'); predictive.disabled=!network;
    if (!network && fields.algorithm.value==='Predictive') fields.algorithm.value='FedAvg';
    [...fields.network_profile.options].forEach(option => option.disabled=!network && ['bursty_congestion','regime_switching'].includes(option.value));
    if (!network && fields.network_profile.selectedOptions[0].disabled) fields.network_profile.value='normal';
    if(network) applyDataset();else ['seed','partition','network_profile'].forEach(key=>fields[key].disabled=false);
    setBusy(busy);
    $('client-quality-label').textContent=network?'Local loss':'Local accuracy';
    $('compare-button').textContent=network?'So sánh 3 cách chọn client':'So sánh 2 cách chọn client';
    $('task-note').textContent=network?'Một mẫu: 12 đặc trưng hiện tại → 1 RTT tick tiếp theo. Dữ liệu là mô phỏng; FL chạy trên phân vùng logic trong cùng backend.':'MNIST dùng CNN. Dữ liệu sẽ được nạp/phân vùng khi chạy; thời gian mạng là mô phỏng.';
    if(network && trainingTarget==='application_link')$('task-note').textContent='Mỗi client giữ telemetry link của mình: 12 đặc trưng → độ trễ một chiều link ứng dụng ở tick kế tiếp. Chọn client FL ngẫu nhiên; model dùng để chấm tuyến, không dùng nhầm nhãn ứng dụng làm RTT tải model.';
    const centralized=fields.algorithm.value==='Centralized';
    fields.client_count.disabled=centralized; $('use-all-clients').disabled=centralized || !pool.length;
    const centralMNIST=centralized && !network;
    $('pool-hint').textContent=centralMNIST?'Đối chứng MNIST học toàn bộ tập train, không chia theo node.':centralized?'Đối chứng tập trung học dữ liệu toàn pool.':`${count(pool.length)} client ACTIVE hợp lệ trong pool.`;
    if(centralMNIST)$('task-note').textContent='MNIST tập trung dùng toàn bộ tập train chuẩn. Phạm vi địa lý chỉ áp dụng khi huấn luyện theo client hoặc bài toán RTT mạng.';
    $('use-all-clients').textContent=fields.pool_mode.value==='regional'?'Dùng tất cả client trong khu vực':'Dùng toàn bộ pool hợp lệ';
    schedulePreview();
}
function poolQuery() {
    const params=new URLSearchParams({scenario_id:fields.scenario_id.value,pool_mode:fields.pool_mode.value,region_radius_km:fields.region_radius_km.value});
    for(const key of ['region_lat','region_lng'])if(fields[key].value.trim()!=='')params.set(key,fields[key].value);
    return params.toString();
}
function applyPool(context) {
    pool=context.candidate_pool;regionInfo=context.training_region;
    trainingTarget=context.default_target || 'fl_rtt';
    fields.client_count.max=String(Math.max(2,pool.length));
    const r=regionInfo;
    $('region-hint').textContent=r.mode==='regional'?`${pool.length}/${r.eligible_clients} client trong bán kính ${r.radius_km} km${r.center_lat==null?'':` quanh (${num(r.center_lat,3)}, ${num(r.center_lng,3)})`}. Khoảng cách chiếu xuống mặt đất tại snapshot; không xác nhận liên kết vô tuyến. Hai client có thể cách nhau tối đa 2 lần bán kính.`:`Toàn bộ ${pool.length} client hợp lệ; không lọc khoảng cách.`;
}
async function refreshPool() {
    const token=++poolRevision, query=poolQuery();
    poolPending=true;acceptedPoolQuery=null;setBusy(busy);++previewToken;
    try {const context=await api(`/api/fl/training-context?${query}`);if(token!==poolRevision || query!==poolQuery())return;applyPool(context);acceptedPoolQuery=query;}
    catch(error){if(token===poolRevision){pool=[];$('region-hint').textContent=error.message;}}
    finally{if(token===poolRevision){poolPending=false;updateTask();}}
}
async function loadScenario() {
    const token=++loadToken, id=fields.scenario_id.value;
    if(!id) return;
    const previousDataset=fields.dataset_id.value;
    try {
        const [,rows]=await Promise.all([refreshPool(),api(`/api/fl/datasets?scenario_id=${id}`)]);
        if(token!==loadToken)return;
        datasets=rows;
        fields.client_count.max=String(Math.max(2,pool.length));
        fields.dataset_id.innerHTML='<option value="">Tạo snapshot mới</option>'+rows.map(row=>`<option value="${row.id}">#${row.id} · ${esc(row.partition)} · ${count(row.client_count)} client · ${count(Object.values(row.counts).reduce((a,b)=>a+b,0))} mẫu</option>`).join('');
        if(rows.some(row=>String(row.id)===previousDataset))fields.dataset_id.value=previousDataset;
        updateTask();
    } catch(error) { message(error.message,true); }
}
function schedulePreview() { clearTimeout(sizingTimer); ++previewToken; sizingTimer=setTimeout(updatePreview,300); }
function range(value) {return value.min===value.max?count(value.min):`${count(value.min)}–${count(value.max)}`;}
async function updatePreview() {
    const token=++previewToken;
    if(poolPending || acceptedPoolQuery!==poolQuery()){$('data-preview').textContent='Đang xác định phạm vi client; chờ cập nhật hoặc kiểm tra tọa độ.';return;}
    if(!validate()) { $('data-preview').textContent='Điền các thông số hợp lệ để xem dự toán.'; return; }
    try {
        const data=await api('/api/fl/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
        if(token!==previewToken)return;
        if(data.task!=='network_delay') { $('data-preview').textContent=data.note; return; }
        $('preview-source').textContent=data.source==='saved_dataset'?'Số lượng đọc từ dataset đã lưu; hỗ trợ cả cách chia tùy biến.':'Dự toán trước khi tạo dataset mới.';
        const stats=[['Tổng mẫu dataset',data.dataset_total],['Train ban đầu trong pool',data.pool_counts.train],['Candidate pool',data.candidate_count],['Mẫu học vòng đầu',range(data.first_round_samples)]];
        const rows=[['Dataset / pool',`${count(data.dataset_client_count)} / ${count(data.candidate_count)} client`],...['train','validation','online','test'].map(split=>[`${split} / client trong pool`,range(data.per_client[split])]),['Validation toàn pool',count(data.pool_counts.validation)],['Future test toàn pool',count(data.pool_counts.test)],['Cấu trúc mẫu','12 đầu vào → 1 đầu ra'],['Model','961 tham số · 3.844 byte FP32'],['Epochs cấu hình riêng',`${count(data.epoch_overrides)} client`]];
        $('data-preview').innerHTML=`<div class="sizing-stats">${stats.map(([label,value])=>`<div class="sizing-stat"><strong>${typeof value==='number'?count(value):value}</strong><span>${label}</span></div>`).join('')}</div><div class="split-bar" aria-hidden="true">${['train','validation','online','test'].map(split=>`<span style="flex:${data.dataset_counts[split]}"></span>`).join('')}</div><p class="note">Train · validation · online · future test</p><dl class="sizing-list">${rows.map(([label,value])=>`<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
        $('launch-hint').textContent=`Mỗi vòng: ${fields.algorithm.value==='Centralized'?'toàn bộ pool':count(fields.client_count.value)+' client'}. Chỉ client hoàn tất đóng góp cập nhật.`;
    } catch(error) { if(token===previewToken) { $('data-preview').textContent=error.message; if(fields.dataset_id.value && /online|round/i.test(error.message)) fieldError('rounds',error.message); } }
}
function renderLive(data) {
    if(Number($('monitor-run').value)!==data.id)return;
    const state=data.progress||{};
    $('live-phase').textContent=`${phases[state.phase]||state.phase} · Vòng ${state.round||0}/${data.target_rounds} · ${state.updated_at?new Date(state.updated_at).toLocaleTimeString('vi-VN'):''}`;
    const clients=Object.entries(state.clients||{});
    if(!clients.length && !terminal(data.status))$('clients').innerHTML='<tr><td colspan="6">Đang chờ backend chọn client cho vòng này.</td></tr>';
    if(clients.length) $('clients').innerHTML=clients.map(([id,client])=>`<tr><td>${esc(id)}</td><td><span class="status-tag ${esc(client.status)}">${esc(client.status)}</span></td><td>${client.samples_used==null?'—':count(client.samples_used)}</td><td>${data.task==='network_delay'?num(client.local_loss,5):num(client.local_accuracy)}</td><td>${num(client.training_duration_s)} s</td><td>${num(client.communication_time_ms)} ms</td></tr>`).join('');
    $('live-events').innerHTML=(state.events||[]).slice(-8).reverse().map(event=>`<li>${esc(new Date(event.at).toLocaleTimeString('vi-VN'))} · ${esc(phases[event.phase]||event.phase)} ${esc(event.client_id||'')} ${esc(event.client_status||'')}</li>`).join('');
    if(state.round!==lastRound || ['round_completed','completed','failed'].includes(state.phase)) {lastRound=state.round;scheduleDetail();}
    if(terminal(data.status)) {$('connection-status').textContent='Đã nhận trạng thái cuối';scheduleDetail();loadDatasetsAfterRun();}
}
let lastDatasetRefresh=0;
async function loadDatasetsAfterRun() {if(Date.now()-lastDatasetRefresh<1500)return;lastDatasetRefresh=Date.now();try {datasets=await api(`/api/fl/datasets?scenario_id=${fields.scenario_id.value}`);const selected=fields.dataset_id.value;fields.dataset_id.innerHTML='<option value="">Tạo snapshot mới</option>'+datasets.map(row=>`<option value="${row.id}">#${row.id} · ${esc(row.partition)} · ${row.client_count} client</option>`).join('');fields.dataset_id.value=selected;}catch{}}
function scheduleDetail() {clearTimeout(detailTimer);detailTimer=setTimeout(refreshDetail,250);}
async function refreshDetail() {
    if(detailBusy || launching)return;detailBusy=true;
    const generation=viewGeneration, selectedId=liveId;
    try {
        if(comparisonId) {
            const comparison=await api(`/api/fl/comparisons/${comparisonId}`);
            if(generation!==viewGeneration || selectedId!==liveId)return;
            const selected=comparison.experiments.find(run=>run.id===Number($('monitor-run').value));
            if(selected) renderDetail(selected);
            if(terminal(comparison.status)){setBusy(false);clearInterval(fallbackTimer);message(`So sánh ${comparison.status}.`);}
        } else if(liveId) {
            const detail=await api(`/api/fl/experiments/${liveId}`);if(generation!==viewGeneration || selectedId!==liveId)return;renderDetail(detail);
            if(terminal(detail.status)){setBusy(false);clearInterval(fallbackTimer);message(detail.error_message||`Huấn luyện ${detail.status}.`,detail.status!=='COMPLETED');}
        }
    } catch(error){message(error.message,true);} finally {detailBusy=false;}
}
function renderDetail(data) {
    const rounds=data.rounds||[],latest=rounds.at(-1),network=data.task==='network_delay';
    $('summary').innerHTML=`Experiment <strong>#${data.id}</strong> · ${esc(data.algorithm)} · ${esc(data.status)} · ${data.completed_rounds}/${data.target_rounds} vòng · <a href="/results.html?${comparisonId?'comparison_id='+encodeURIComponent(comparisonId):'experiment_id='+data.id}">Phân tích kết quả</a>`;
    $('rounds').innerHTML=`<div class="round"><progress max="${data.target_rounds}" value="${data.completed_rounds}" aria-label="Vòng đã hoàn tất"></progress><span>${network?'MAE '+num(latest?.prediction_metrics?.mae_ms)+' ms':'Accuracy '+num(latest?.accuracy)} · ${num(latest?.round_duration_s)} s/vòng mô phỏng</span></div>`;
    const values=rounds.map(row=>network?row.prediction_metrics?.mae_ms:row.accuracy).filter(Number.isFinite);
    if(values.length>1){const min=Math.min(...values),max=Math.max(...values),points=values.map((value,i)=>`${10+980*i/(values.length-1)},${120-100*(value-min)/(max-min||1)}`).join(' ');$('quality-chart').innerHTML=`<svg viewBox="0 0 1000 140" role="img" aria-label="${network?'MAE':'Accuracy'} qua ${values.length} vòng"><polyline points="${points}" fill="none" stroke="#8de5be" stroke-width="3"/></svg><p class="note">${network?'MAE (ms)':'Accuracy'} theo vòng · min ${num(min,6)} · max ${num(max,6)} · trục tự điều chỉnh</p>`;}
    if(latest && terminal(data.status)) $('clients').innerHTML=latest.clients.map(client=>`<tr><td>${esc(client.client_id)}</td><td>${esc(client.status)}</td><td>${count(client.samples_used)}</td><td>${network?num(client.local_loss,5):num(client.local_accuracy)}</td><td>${num(client.training_duration_s)} s</td><td>${num(client.communication_time_ms)} ms</td></tr>`).join('');
}
function monitor(runs, comparison=null) {
    ++viewGeneration;
    watched.forEach(stop=>stop());watched=[];runStates.clear();runs.forEach(run=>runStates.set(run.id,run));clearInterval(fallbackTimer);comparisonId=comparison;renderComparison();
    $('monitor-run').innerHTML=runs.map(run=>`<option value="${run.id}">#${run.id} · ${esc(run.algorithm)}</option>`).join('');
    liveId=runs[0].id;lastRound=-1;
    $('quality-chart').replaceChildren();$('live-events').replaceChildren();
    $('clients').innerHTML='<tr><td colspan="6">Đang chờ backend chọn client.</td></tr>';
    localStorage.setItem('sagsin-training-monitor',JSON.stringify({ids:runs.map(run=>run.id),comparison,scenario:Number(fields.scenario_id.value)}));
    runs.forEach(run=>watched.push(watchTraining(run.id,data=>{runStates.set(data.id,data);renderComparison();renderLive(data);if(terminal(data.status))scheduleDetail();},text=>{$('connection-status').textContent=text;})));
    fallbackTimer=setInterval(refreshDetail,10000);refreshDetail();
}
async function queue(comparison) {
    if(busy || poolPending || acceptedPoolQuery!==poolQuery() || !validate(true))return;
    launching=true;++viewGeneration;
    const data=payload(); if(data.algorithm==='Centralized') data.client_count=Math.max(2,Math.min(pool.length,data.client_count));
    setBusy(true);
    try {await api('/api/fl/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}catch(error){launching=false;setBusy(false);message(error.message,true);return;}
    setBusy(true);message(comparison?'Đang tạo dataset và các phương án so sánh…':'Đang tạo dataset và experiment…');
    try {
        if(comparison)delete data.algorithm;
        const result=await api(comparison?'/api/fl/comparisons':'/api/fl/experiments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        launching=false;
        monitor(comparison?result.experiments:[result],comparison?result.comparison_id:null);message('Đã xếp hàng. Tiến trình sẽ tự cập nhật.');
    } catch(error){launching=false;setBusy(false);message(error.message,true);}
}
form.addEventListener('submit',event=>{event.preventDefault();queue(false);});
$('compare-button').addEventListener('click',()=>queue(true));
$('use-all-clients').addEventListener('click',()=>{fields.client_count.value=pool.length;schedulePreview();});
form.addEventListener('input',event=>{if(['pool_mode','region_radius_km','region_lat','region_lng'].includes(event.target.name)){acceptedPoolQuery=null;setBusy(busy);}schedulePreview();});
form.addEventListener('change',event=>{if(event.target===fields.scenario_id)loadScenario();else if(['pool_mode','region_radius_km','region_lat','region_lng'].includes(event.target.name))refreshPool();else if(event.target===fields.dataset_id){applyDataset();schedulePreview();}else if([fields.task,fields.algorithm].includes(event.target))updateTask();else schedulePreview();});
$('monitor-run').addEventListener('change',async()=>{liveId=Number($('monitor-run').value);lastRound=-1;$('quality-chart').replaceChildren();try{renderLive(await api(`/api/fl/experiments/${liveId}/progress`));}catch{}scheduleDetail();});
window.addEventListener('pageshow',event=>{if(event.persisted)init();});
window.addEventListener('focus',async()=>{
    if(!fields.scenario_id.value)return;
    await refreshPool();
});
window.addEventListener('pagehide',()=>{watched.forEach(stop=>stop());clearInterval(fallbackTimer);});
async function init() {
    try {
        const scenarios=await api('/api/simulations/scenarios');
        fields.scenario_id.innerHTML=scenarios.map(row=>`<option value="${row.id}">${esc(row.name)}</option>`).join('');
        if(!scenarios.length){message('Chưa có scenario.',true);setBusy(true);return;}
        let saved;try{saved=JSON.parse(localStorage.getItem('sagsin-training-monitor'));}catch{}
        if(saved && scenarios.some(row=>row.id===saved.scenario))fields.scenario_id.value=saved.scenario;
        await loadScenario();
        const requested=Number(new URLSearchParams(location.search).get('experiment_id'));
        const ids=requested?[requested]:saved?.ids;
        if(ids?.length) {
            try {
                const previous=await api(`/api/fl/experiments/${ids[0]}`);
                if(String(fields.scenario_id.value)!==String(previous.scenario_id)) {fields.scenario_id.value=previous.scenario_id;await loadScenario();}
                for(const [key,value] of Object.entries(previous.config||{})) if(fields[key] && ['string','number'].includes(typeof value)) fields[key].value=value;
                fields.pool_mode.value=previous.config?.pool_mode||'all';
                for(const key of ['region_lat','region_lng'])fields[key].value=previous.config?.[key]??'';
                fields.algorithm.value=previous.algorithm;
                fields.dataset_id.value=previous.dataset_id||'';await refreshPool();updateTask();
            } catch {}
        }
        if(ids?.length){try{const runs=await Promise.all(ids.map(id=>api(`/api/fl/experiments/${id}/progress`)));setBusy(runs.some(run=>!terminal(run.status)));monitor(runs,requested?null:saved.comparison);}catch{localStorage.removeItem('sagsin-training-monitor');}}
    } catch(error){message(error.message,true);setBusy(true);}
}
init();

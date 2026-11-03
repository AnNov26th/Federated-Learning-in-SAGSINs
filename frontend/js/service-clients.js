import * as THREE from 'three';
import {latLngToVector3} from './3d/coordinates.js';
import {createLiveArc,sampleLivePath} from './3d/live-links.js';
import {createServicePath} from './3d/service-path.js';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const terminal=new Set(['completed','ended','rejected','failed']);
const names={ringing:'Đang đổ chuông',connecting:'Đang kết nối',active:'Đang hoạt động',transmitting:'Đang truyền',awaiting_ack:'Chờ đích xác nhận',confirming:'Đang truyền ACK về',completed:'Đã nhận ACK · hoàn tất',ended:'Đã kết thúc',rejected:'Đã từ chối',failed:'Thất bại · chưa xác nhận',waiting:'Chờ tuyến / băng thông',interrupted:'Mất kết nối điều khiển'};
const devices={network_gateway:'Gateway mô phỏng',smartphone:'Điện thoại',satellite_terminal:'Đầu cuối vệ tinh',emergency_radio:'Thiết bị cứu hộ',iot_sensor:'Cảm biến IoT'};
const deviceIcons={network_gateway:'network-wired',smartphone:'mobile-screen-button',satellite_terminal:'satellite-dish',emergency_radio:'walkie-talkie',iot_sensor:'microchip'};

export function setupServiceClients({scene3D,nodeMarkers,createMarker,flyGlobeToMarker,routing}) {
    let state={clients:[],sessions:[]},generation=0,selected=null,viewedSession=null,drawKey='',busy=false;
    const sockets=new Map(),markers=new Map(),pending=new Map();
    const removedClients=new Set();
    const livePaths=[];
    const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
    const layer=new THREE.Group();scene3D.earth.add(layer);
    const message=text=>{$('service-feedback').textContent=text;};
    const scenario=()=>Number($('routing-scenario').value);
    const label=id=>state.clients.find(c=>c.id===id)?.name||`Client ${id}`;
    async function api(path,options) {
        const response=await fetch('/api/service'+path,options),body=await response.json();
        if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Yêu cầu không hợp lệ.');
        return body;
    }
    function chooseOptions(element,clients,value) {
        const signature=clients.map(c=>`${c.id}:${c.name}`).join('|');
        if(element.dataset.options!==signature){element.innerHTML=clients.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');element.dataset.options=signature;}
        if(clients.some(c=>c.id===Number(value)))element.value=value;
    }
    function render() {
        for(const marker of nodeMarkers){marker.userData.service_reserved_mbps=0;marker.userData.service_connections=0;}
        for(const session of state.sessions){
            if(terminal.has(session.state))continue;
            for(const [i,route] of (session.result.routes||[]).entries()){
                const rate=session.result.rates_mbps?.[i]||0;
                if(!rate)continue;
                for(const id of new Set(route.path)){const data=nodeMarkers.find(m=>m.userData.id===id)?.userData;if(data){data.service_reserved_mbps+=rate;data.service_connections++;}}
            }
        }
        chooseOptions($('service-source'),state.clients,selected||$('service-source').value);
        selected=Number($('service-source').value)||null;
        chooseOptions($('service-peer'),state.clients.filter(c=>c.id!==selected),$('service-peer').value);
        $('service-peer').disabled=['Emergency','Watch Video'].includes($('service-kind').value);
        $('service-session-form').querySelector('button').disabled=!selected||busy;
        const connectedCount=[...sockets.values()].filter(s=>s.ws.readyState===WebSocket.OPEN).length;
        $('service-connection').textContent=connectedCount===state.clients.length?`${connectedCount} client đã kết nối`:`Đang kết nối ${connectedCount}/${state.clients.length} client…`;
        const activeClientCount=state.clients.filter(c=>state.sessions.some(s=>!terminal.has(s.state)&&(s.source_id===c.id||s.target_id===c.id))).length;
        $('service-client-count').textContent=`${state.clients.length} client · ${activeClientCount} đang có phiên`;
        const clientContent=state.clients.map(c=>{
            const sessions=state.sessions.filter(s=>s.source_id===c.id||s.target_id===c.id);
            const live=sessions.filter(s=>!terminal.has(s.state));
            return `<article class="service-client-item${c.id===selected?' selected':''}" role="listitem"><button class="service-client-info" type="button" data-focus-client="${c.id}" aria-pressed="${c.id===selected}"><span class="service-client-avatar" aria-hidden="true"><i class="fa-solid fa-${deviceIcons[c.device]||'microchip'}"></i></span><span class="service-client-body"><span class="service-client-top"><strong title="${esc(c.name)}">${esc(c.name)}</strong><span class="service-client-status" data-online="${c.online}">${c.online?'Online':'Offline'}</span></span><span class="service-client-meta">${esc(devices[c.device]||c.device)} · <span>${c.lat.toFixed(2)}°, ${c.lng.toFixed(2)}°</span></span><span class="service-client-activity" data-live="${live.length>0}">${live.length?`${live.length} phiên · ${esc(names[live[0].state]||live[0].state)}`:sessions.length?`${sessions.length} phiên đã lưu`:'Chưa có phiên'}</span></span></button><button class="service-client-delete" type="button" data-delete-client="${c.id}" aria-label="Xóa ${esc(c.name)}" title="Xóa client và kết thúc các phiên liên quan" ${busy?'disabled':''}><i class="fa-solid fa-trash-can" aria-hidden="true"></i></button></article>`;
        }).join('')||'<div class="drop-empty"><i class="fa-solid fa-location-dot" aria-hidden="true"></i><span>Chưa có client</span><small>Nhấn Đặt client để bắt đầu</small></div>';
        const focusedClient=document.activeElement?.closest('[data-focus-client],[data-delete-client]');
        const clientFocusSelector=focusedClient?(focusedClient.dataset.deleteClient?`[data-delete-client="${focusedClient.dataset.deleteClient}"]`:`[data-focus-client="${focusedClient.dataset.focusClient}"]`):null;
        if($('service-client-list').innerHTML!==clientContent){
            $('service-client-list').innerHTML=clientContent;
            if(clientFocusSelector)$('service-client-list').querySelector(clientFocusSelector)?.focus({preventScroll:true});
        }
        const focused=document.activeElement?.closest('[data-session-action]');
        const focusKey=focused?`${focused.dataset.sessionAction}:${focused.dataset.id}`:null;
        const content=state.sessions.map(s=>{
            const r=s.result,source=label(s.source_id),target=s.target_id?label(s.target_id):'Máy chủ GROUND';
            const controls=s.state==='ringing'?`<button type="button" data-session-action="accept" data-id="${s.id}" data-actor="${s.target_id}">${esc(target)} nhận</button><button type="button" data-session-action="reject" data-id="${s.id}" data-actor="${s.target_id}">Từ chối</button>`:'';
            const rates=(r.rates_mbps||[]).map((v,i)=>`${i?'B → A':'A → B'}: ${v.toFixed(3)} Mbps`).join(' · ')||'Không giữ băng thông';
            const paths=(r.routes||[]).map((route,i)=>`<p>${i?'B → A':'A → B'}: ${esc(route.path.join(' → '))}<br>${route.distance_km.toFixed(0)} km · ${route.application.estimated_one_way_ms.toFixed(1)} ms hiện tại · ${route.application.latency_budget_met?'trong':'vượt'} ngân sách demo${route.application.planning_one_way_ms!=null?`<br>Ước tính khi chọn: ${route.application.planning_one_way_ms.toFixed(1)} ms · ${route.hop_count} hop`:''}${route.motion_clock_s!=null?`<br>Vị trí backend: t = ${route.motion_clock_s.toFixed(1)} s`:''}</p>`).join('');
            return `<article class="service-card" data-service-id="${s.id}"><h5>#${s.id} · ${esc(s.service)} · ${esc(source)} ↔ ${esc(target)}</h5><p class="service-state">${names[s.state]||esc(s.state)}</p><p>${esc(r.reason)}</p><p>${rates}</p>${r.quality==='degraded'&&!terminal.has(s.state)?'<p>Chất lượng suy giảm: thiếu tốc độ yêu cầu hoặc vượt ngân sách độ trễ demo.</p>':''}<p>Đã truyền: ${(r.delivered_mbit||0).toFixed(3)} Mbit · đổi tuyến: ${r.reroutes||0}</p>${paths?`<details><summary>Tuyến ${terminal.has(s.state)?'đã sử dụng':'và chất lượng'}</summary>${paths}</details>`:''}<div class="service-actions">${controls}${!terminal.has(s.state)?`<button type="button" data-session-action="end" data-id="${s.id}" data-actor="${s.source_id}">Kết thúc / hủy</button>`:''}</div></article>`;
        }).join('')||'<p class="routing-help">Chưa có phiên. Chọn client và dịch vụ để bắt đầu.</p>';
        if($('service-session-list').innerHTML!==content){
            const open=[...$('service-session-list').querySelectorAll('details[open]')].map(d=>d.closest('article').dataset.serviceId);
            $('service-session-list').innerHTML=content;
            for(const id of open)$('service-session-list').querySelector(`[data-service-id="${id}"] details`)?.setAttribute('open','');
            if(focusKey){const [action,id]=focusKey.split(':');$('service-session-list').querySelector(`[data-session-action="${action}"][data-id="${id}"]`)?.focus({preventScroll:true});}
        }
        draw();
    }
    function dispose(object){object.traverse(n=>{n.geometry?.dispose();if(n.material){n.material.map?.dispose();n.material.dispose();}});object.removeFromParent();}
    function draw() {
        for(const [id,marker] of markers)if(!state.clients.some(c=>c.id===id)){dispose(marker);markers.delete(id);}
        for(const client of state.clients){
            let marker=markers.get(client.id);
            if(!marker){marker=createMarker(0xff72d0,255,114,208,1.6);marker.userData.serviceClientId=client.id;scene3D.earth.add(marker);markers.set(client.id,marker);}
            marker.position.copy(latLngToVector3(client.lat,client.lng));
        }
        const key=JSON.stringify([selected,viewedSession,state.clients.map(c=>[c.id,c.lat,c.lng]),state.sessions.map(s=>[s.id,s.state,s.result.phase,s.result.rates_mbps?.some(rate=>rate>0),s.result.routes?.map(r=>r.path)])]);
        if(key===drawKey)return;drawKey=key;
        livePaths.length=0;
        while(layer.children.length)dispose(layer.children[0]);
        const shown=new Set();
        // Keep the latest route for each connection after completion. Active
        // routes take priority over duplicate history for the same endpoints.
        const ordered=[...state.sessions.filter(s=>!terminal.has(s.state)),...state.sessions.filter(s=>terminal.has(s.state))];
        for(const session of ordered){
            for(const [index,route] of (session.result.routes||[]).entries()){
                const connection=`${session.source_id}:${session.target_id||'server'}:${session.service}:${index}`;
                if(shown.has(connection)&&session.id!==viewedSession)continue;
                shown.add(connection);
                const backwards=index===1||['ack','ack_in_flight'].includes(session.result.phase)||session.service==='Watch Video';
                const first=state.clients.find(c=>c.id===(backwards?session.target_id:session.source_id));
                const last=state.clients.find(c=>c.id===(backwards?session.source_id:session.target_id));
                const historic=terminal.has(session.state);
                const color=backwards?0xffc66b:0x64ded2;
                const path=createServicePath({route,first,last,
                    nodePosition:id=>nodeMarkers.find(marker=>marker.userData.id===id)?.position,
                    clientPosition:client=>markers.get(client.id)?.position||latLngToVector3(client.lat,client.lng),
                    fallbackPosition:node=>latLngToVector3(node.lat,node.lng,node.alt),createArc:createLiveArc,
                    style:{color,dashed:historic,opacity:historic?.4:.9}});
                for(const arc of path.segments)layer.add(arc.line);
                const flowing=!historic&&(session.result.rates_mbps?.[index]||0)>0;
                let packet=null;
                if(flowing){packet=new THREE.Mesh(new THREE.SphereGeometry(.012,8,8),new THREE.MeshBasicMaterial({color}));layer.add(packet);}
                livePaths.push({...path,packet,started:performance.now()});
            }
        }
    }
    scene3D.earth.userData.advanceServiceRoutes=()=>{
        const now=performance.now();
        for(const path of livePaths){
            path.update();
            if(path.packet)path.packet.visible=!reducedMotion.matches&&sampleLivePath(path.segments,((now-path.started)%4000)/4000,path.packet.position);
        }
    };
    function consume(next,epoch){
        if(epoch!==generation)return;
        const clients=next.clients.filter(c=>!removedClients.has(c.id)),ids=new Set(clients.map(c=>c.id));
        state={clients,sessions:next.sessions.filter(s=>ids.has(s.source_id)&&(!s.target_id||ids.has(s.target_id)))};
        for(const [id,entry] of sockets)if(!ids.has(id)){clearInterval(entry.timer);sockets.delete(id);entry.ws.close();}
        render();
    }
    function connect(client,epoch){
        if(sockets.has(client.id))return;
        const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/service/clients/${client.id}/ws`);
        const entry={ws,timer:null};sockets.set(client.id,entry);
        ws.onopen=()=>{ws.send(JSON.stringify({type:'register',token:client.token}));entry.timer=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'heartbeat'}));},10000);render();};
        ws.onmessage=event=>{const data=JSON.parse(event.data);if(data.type==='state')consume(data,epoch);if(data.request_id){const request=pending.get(data.request_id);if(request){clearTimeout(request.timer);pending.delete(data.request_id);data.type==='error'?request.reject(new Error(data.message)):request.resolve(data);}}else if(data.type==='error')message(data.message);};
        ws.onclose=event=>{clearInterval(entry.timer);if(sockets.get(client.id)===entry)sockets.delete(client.id);if(epoch===generation){render();if(event.code===1008){api(`/state?scenario_id=${scenario()}`).then(next=>consume(next,epoch)).catch(()=>{});return;}setTimeout(()=>{if(epoch===generation&&state.clients.some(c=>c.id===client.id))connect(client,epoch);},3000);}};
        ws.onerror=()=>message('Mất kênh điều khiển; đang thử kết nối lại.');
    }
    function send(actor,data){
        const ws=sockets.get(Number(actor))?.ws;
        if(!ws||ws.readyState!==WebSocket.OPEN)return Promise.reject(new Error('Client chưa có WebSocket. Chờ kết nối lại.'));
        const id=crypto.randomUUID();
        return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Chưa nhận phản hồi; kiểm tra trạng thái trước khi thử lại.'));},15000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({...data,request_id:id}));});
    }
    async function reload(){
        const epoch=++generation;
        for(const entry of sockets.values()){clearInterval(entry.timer);entry.ws.close();}sockets.clear();
        for(const marker of markers.values())dispose(marker);markers.clear();drawKey='';
        if(!scenario())return;
        try{const next=await api(`/state?scenario_id=${scenario()}`);if(epoch!==generation)return;consume(next,epoch);for(const c of next.clients)connect(c,epoch);}catch(error){message(error.message);}
    }
    async function addClient(lat,lng,name){
        if(!scenario())throw new Error('Chọn scenario trước.');
        const client=await api('/clients',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_id:scenario(),name:name||$('service-client-name').value.trim()||`Client ${state.clients.length+1}`,lat,lng,device:$('service-client-device').value})});
        state.clients.push(client);selected=client.id;connect(client,generation);render();
        $('service-client-name').value=`Client ${state.clients.length+1}`;
        routing.openClientPanel();message(`Đã đặt ${client.name}. Chọn dịch vụ bên dưới.`);
        return client;
    }
    async function task(button,work){if(busy)return;busy=true;if(button)button.disabled=true;try{await work();}catch(error){message(error.message);}finally{busy=false;if(button)button.disabled=false;render();}}
    async function deleteClient(id){
        const client=state.clients.find(c=>c.id===id);if(!client)return;
        await api(`/clients/${id}`,{method:'DELETE'});
        removedClients.add(id);
        const entry=sockets.get(id);if(entry){clearInterval(entry.timer);sockets.delete(id);entry.ws.close();}
        state.clients=state.clients.filter(c=>c.id!==id);
        state.sessions=state.sessions.filter(s=>s.source_id!==id&&s.target_id!==id);
        if(selected===id)selected=state.clients[0]?.id||null;
        if(!state.sessions.some(s=>s.id===viewedSession))viewedSession=null;
        render();message(`Đã xóa ${client.name} và kết thúc các phiên liên quan.`);
        $('service-client-list').querySelector('[data-focus-client]')?.focus({preventScroll:true});
    }
    $('service-client-form').addEventListener('submit',event=>{event.preventDefault();task(event.submitter,()=>addClient(Number($('service-client-lat').value),Number($('service-client-lng').value)));});
    $('service-session-form').addEventListener('submit',event=>{event.preventDefault();task(event.submitter,async()=>{const peer=!['Emergency','Watch Video'].includes($('service-kind').value);await send(selected,{type:'start',request:{service:$('service-kind').value,target_id:peer?Number($('service-peer').value):null,policy:$('service-policy').value}});message('Đã tạo phiên; cuộc gọi cần bên nhận chấp nhận.');});});
    $('service-source').addEventListener('change',()=>{selected=Number($('service-source').value);render();});
    $('service-kind').addEventListener('change',render);
    $('service-session-list').addEventListener('click',event=>{const button=event.target.closest('[data-session-action]');if(button)task(button,()=>send(button.dataset.actor,{type:button.dataset.sessionAction,session_id:Number(button.dataset.id)}));else if(event.target.closest('summary')){viewedSession=Number(event.target.closest('[data-service-id]').dataset.serviceId);draw();}});
    $('service-client-list').addEventListener('click',event=>{const remove=event.target.closest('[data-delete-client]');if(remove){task(remove,()=>deleteClient(Number(remove.dataset.deleteClient)));return;}const button=event.target.closest('[data-focus-client]');if(button)focus(Number(button.dataset.focusClient));});
    $('service-demo-pair').addEventListener('click',event=>task(event.currentTarget,async()=>{
        const response=await fetch('/api/nodes'),payload=await response.json();
        const nodes=payload.data.filter(n=>n.scenario_id===scenario()&&n.type==='GROUND'&&n.status==='ACTIVE');
        let pair=null,best=-1;
        for(const a of nodes)for(const b of nodes){if(a.lat*b.lat>=0)continue;const score=latLngToVector3(a.lat,a.lng).distanceToSquared(latLngToVector3(b.lat,b.lng));if(score>best){best=score;pair=[a,b];}}
        if(!pair)throw new Error('Scenario cần trạm GROUND ở cả bán cầu Bắc và Nam.');
        const first=await addClient(pair[0].lat,pair[0].lng,`Client Bắc/Nam A · ${pair[0].id}`);
        await addClient(pair[1].lat,pair[1].lng,`Client Bắc/Nam B · ${pair[1].id}`);
        selected=first.id;render();message('Đã đặt hai client ở hai bán cầu gần trạm truy cập. Chọn Video call → Bắt đầu → bên nhận nhận cuộc gọi.');
    }));
    function focus(id){selected=id;render();routing.openClientPanel();flyGlobeToMarker(markers.get(id));}
    $('routing-scenario').addEventListener('change',reload);
    $('service-benchmark').addEventListener('toggle',async()=>{
        if(!$('service-benchmark').open)return;
        try{
            const result=await api(`/benchmark?scenario_id=${scenario()}`);
            if(!result.available){$('service-benchmark-summary').textContent='Chưa có báo cáo hoàn tất cho scenario này.';return;}
            $('service-benchmark-summary').textContent=`${result.seeds} seed · chọn tại t, chấm tại t+1. Độ trễ trung bình chỉ tính tuyến còn khả dụng; đọc cùng tỷ lệ kết nối/QoS.`;
            const labels={static:'Tĩnh',current:'Hiện tại',predictive:'FL'};
            $('service-benchmark-table').innerHTML=`<div class="service-benchmark-scroll"><table><thead><tr><th>Chính sách</th><th>MAE link</th><th>Kết nối</th><th>Đạt QoS</th><th>Trễ 1 chiều</th></tr></thead><tbody>${result.aggregates.map(row=>`<tr><td>${labels[row.policy]||esc(row.policy)}</td><td>${row.next_tick_link_mae_ms_mean.toFixed(3)} ms</td><td>${(row.availability_fraction_mean*100).toFixed(1)}%</td><td>${(row.qos_fraction_mean*100).toFixed(1)}%</td><td>${row.mean_one_way_ms_mean==null?'—':row.mean_one_way_ms_mean.toFixed(1)+' ms'}</td></tr>`).join('')}</tbody></table></div><p class="routing-help">Cùng client, tải và topology; FL không được xem trạng thái tương lai khi chọn tuyến. Chưa suy ra FL luôn tốt hơn baseline.</p><a href="/api/service/benchmark/report?run=${encodeURIComponent(result.run)}" target="_blank" rel="noopener">Mở báo cáo đầy đủ</a>`;
        }catch(error){$('service-benchmark-summary').textContent=error.message;}
    });
    document.querySelector('[data-simulation-panel="route"]').addEventListener('click',event=>{
        if(!state.sessions.length)return;
        event.stopImmediatePropagation();routing.openClientPanel();
        const latest=$('service-session-list').querySelector('details');
        if(latest){latest.open=true;viewedSession=state.sessions[0].id;draw();}
        $('service-session-list').scrollIntoView({block:'start'});
    },true);
    const initial=setInterval(()=>{if(scenario()){clearInterval(initial);reload();}},300);
    window.addEventListener('pagehide',()=>{generation++;for(const entry of sockets.values()){clearInterval(entry.timer);entry.ws.close();}});
    return {addClient:async(lat,lng)=>{try{return await addClient(lat,lng);}catch(error){message(error.message);routing.openClientPanel();}},markers,focus};
}

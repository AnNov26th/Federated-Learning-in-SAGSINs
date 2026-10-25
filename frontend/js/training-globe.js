import * as THREE from 'three';
import {createLiveArc} from './3d/live-links.js';
import {watchTraining, phases, terminal} from './training-stream.js';

export function setupTrainingGlobe({scene3D, nodeMarkers, container, scenarioSelect}) {
    const panel=document.createElement('aside');panel.className='training-live-overlay';panel.hidden=true;
    panel.innerHTML='<strong>FL trực tiếp</strong><p class="training-status" role="status"></p><p class="training-stats"></p><p class="training-caption">Trao đổi model minh họa với bộ tổng hợp logic; không biểu diễn tuyến hoặc gói tin thực.</p><a class="training-results" href="/fl.html">Mở bảng huấn luyện</a>';
    container.appendChild(panel);
    panel.addEventListener('pointerdown', event => event.stopPropagation());
    panel.addEventListener('click', event => event.stopPropagation());
    const group=new THREE.Group();scene3D.earth.add(group);
    const anchor=new THREE.Vector3(0,3.1,0);
    let current=null, stop, currentId, selectedKey='', entries=[], fetching=false, elapsed=0;
    const notified = new Set();
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    function clear() {
        group.traverse(object=>{object.geometry?.dispose();if(object.material)object.material.dispose();});
        group.clear();entries=[];selectedKey='';
    }
    function render(data) {
        current=data;panel.hidden=false;
        const state=data.progress||{};
        const clients=Object.values(state.clients||{});
        panel.querySelector('.training-stats').textContent=`Đang học: ${clients.filter(client=>client.status==='TRAINING').length} · Hoàn tất: ${clients.filter(client=>client.status==='COMPLETED').length} · Lỗi: ${clients.filter(client=>['DROPPED','TIMEOUT'].includes(client.status)).length}`;
        panel.querySelector('.training-status').textContent=`#${data.id} · ${data.algorithm} · ${phases[state.phase]||state.phase} · ${state.round||0}/${data.target_rounds} vòng · ${Object.keys(state.clients||{}).length} client`;
        panel.querySelector('.training-results').href=`/fl.html?experiment_id=${data.id}`;
        if(terminal(data.status)){
            panel.querySelector('.training-caption').textContent='Đã nhận trạng thái cuối. Đường FL là minh họa, không phải tuyến vật lý.';
            if(data.status==='COMPLETED' && data.task==='network_delay' && !notified.has(data.id)) {
                notified.add(data.id);window.dispatchEvent(new CustomEvent('fl-checkpoint-ready',{detail:{scenario_id:data.scenario_id,experiment_id:data.id}}));
            }
            clear();return;
        }
        const key=`${data.id}:${state.round}:${(state.selected||[]).join(',')}`;
        if(key!==selectedKey){
            clear();selectedKey=key;
            const hub=new THREE.Mesh(new THREE.OctahedronGeometry(.055),new THREE.MeshBasicMaterial({color:0xbdabff}));hub.position.copy(anchor);group.add(hub);
            for(const id of state.selected||[]) {
                const marker=nodeMarkers.find(node=>node.userData.id===id);if(!marker)continue;
                const halo=new THREE.Mesh(new THREE.SphereGeometry(.035,10,8),new THREE.MeshBasicMaterial({color:0xffcf7c,wireframe:true,transparent:true,opacity:.9}));group.add(halo);
                const arc=createLiveArc({from:()=>marker.position,to:()=>anchor,color:0xbdabff,dashed:true,opacity:.55});group.add(arc.line);
                const packet=new THREE.Mesh(new THREE.SphereGeometry(.012,6,6),new THREE.MeshBasicMaterial({color:0xbdabff}));group.add(packet);
                entries.push({id,marker,halo,arc,packet});
            }
        }
    }
    async function discover() {
        if(fetching || !scenarioSelect.value)return;fetching=true;
        const scenario=scenarioSelect.value;
        try {
            const response=await fetch(`/api/fl/activity?scenario_id=${encodeURIComponent(scenarioSelect.value)}`);
            if(!response.ok)throw new Error('Không đọc được tiến trình');
            const rows=(await response.json()).data||[];
            if(scenarioSelect.value!==scenario)return;
            const chosen=rows.find(row=>row.status==='RUNNING')||rows.find(row=>!terminal(row.status))||rows[0];
            if(!chosen){stop?.();currentId=null;current=null;clear();panel.hidden=true;return;}
            if(chosen.id!==currentId){stop?.();currentId=chosen.id;render(chosen);stop=watchTraining(chosen.id,render,text=>{panel.querySelector('.training-caption').textContent=`${text}. Đường FL chỉ là minh họa, không phải tuyến vật lý.`;});}
            else if(terminal(chosen.status))render(chosen);
        } catch {if(!panel.hidden)panel.querySelector('.training-caption').textContent='Không lấy được tiến trình mới; đang thử kết nối lại. Hình vẽ không phải gói tin thực.';}
        finally{fetching=false;}
    }
    scene3D.earth.userData.advanceTraining=delta=>{
        elapsed+=delta;
        for(const item of entries){
            const status=current?.progress?.clients?.[item.id]?.status;
            const color=['TIMEOUT','DROPPED'].includes(status)?0xff859b:status==='TRAINING'?0xffcf7c:status==='COMPLETED'?0x85efbf:0xbdabff;
            item.halo.material.color.setHex(color);item.halo.position.copy(item.marker.position);item.arc.update();
            item.packet.visible=!reduced.matches && ['TRAINING','COMPLETED'].includes(status);
            if(item.packet.visible)item.arc.sample(status==='COMPLETED'?(elapsed*.35)%1:1-(elapsed*.35)%1,item.packet.position);
        }
    };
    scenarioSelect.addEventListener('change',()=>{stop?.();currentId=null;current=null;clear();panel.hidden=true;discover();});
    const timer=setInterval(discover,3000);discover();
    window.addEventListener('pagehide',()=>{stop?.();clearInterval(timer);clear();});
}

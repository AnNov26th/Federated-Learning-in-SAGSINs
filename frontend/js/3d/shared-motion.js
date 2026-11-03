import * as THREE from 'three';
import {latLngToVector3} from './coordinates.js';

export function setupSharedMotion({nodeMarkers,scenario,earth}) {
    let samples=new Map(),elapsed=0,clock=null,scenarioId=null,busy=false,horizon=2;
    async function refresh(){
        const id=Number(scenario());if(!id||busy)return;busy=true;
        try{
            const response=await fetch(`/api/motion?scenario_id=${id}`);
            if(!response.ok)throw new Error('Không tải được vị trí backend');
            const data=await response.json();if(Number(scenario())!==id)return;
            if(scenarioId===id&&clock===data.clock_s)return;
            scenarioId=id;clock=data.clock_s;horizon=data.horizon_s;elapsed=0;
            samples=new Map(data.nodes.map(n=>[n.id,{from:latLngToVector3(n.lat,n.lng,n.alt),to:latLngToVector3(n.next.lat,n.next.lng,n.next.alt)}]));
            earth.userData.motionClock=clock;earth.userData.motionSynchronized=true;
            earth.userData.motionTopology={scenario_id:id,links:data.contacts||[],total_links:data.total_contacts,neighbors_shown:2,
                key:`${id}:motion:${(data.contacts||[]).map(e=>e.id).sort().join(',')}`};
            const status=document.getElementById('motion-sync-status');if(status)status.textContent=`Vị trí đồng bộ · t = ${clock.toFixed(0)} s`;
        }catch{earth.userData.motionSynchronized=false;const status=document.getElementById('motion-sync-status');if(status)status.textContent='Mất đồng bộ vị trí · tạm giữ vị trí gần nhất';}
        finally{busy=false;}
    }
    const timer=setInterval(refresh,2000);refresh();
    window.addEventListener('pagehide',()=>clearInterval(timer));
    const temp=new THREE.Vector3();
    return {refresh,advance(seconds){
        elapsed=Math.min(horizon,elapsed+seconds);
        for(const marker of nodeMarkers){
            const sample=samples.get(marker.userData.id);
            if(!sample||earth.userData.deployedNodePositions?.has(marker.userData.id))continue;
            const t=elapsed/horizon;
            temp.lerpVectors(sample.from,sample.to,t).normalize().multiplyScalar(THREE.MathUtils.lerp(sample.from.length(),sample.to.length(),t));
            marker.position.copy(temp);
        }
    }};
}

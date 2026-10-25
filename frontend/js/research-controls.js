export function setupResearchControls({api,scenarioSelect,refreshNodes,loadContext,updateOptions,refreshEvents}) {
    const $=id=>document.getElementById(id);
    let current=null,polling=false;
    function show(state){
        current=state;$('research-state').textContent=`Đồng hồ ${state.sim_time_s.toFixed(1)} s · ${state.running?'đang chạy':'tạm dừng'}`;
        $('research-clock').textContent=state.running?'Tạm dừng đồng hồ':'Chạy đồng hồ';
        if(document.activeElement!==$('research-condition'))$('research-condition').value=state.conditions;
    }
    async function poll(){
        if(polling || $('research-panel').hidden)return;polling=true;
        try{show(await api(`/api/research/${scenarioSelect.value}`));await refreshEvents();}
        catch(error){$('research-state').textContent=error.message;}finally{polling=false;}
    }
    async function control(data){
        try{show(await api(`/api/research/${scenarioSelect.value}/control`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}));await refreshEvents();}
        catch(error){$('research-state').textContent=error.message;}
    }
    $('research-create').addEventListener('click',async()=>{
        $('research-create').disabled=true;
        try{
            const state=await api('/api/research/region',{method:'POST'});
            await refreshNodes();await loadContext();scenarioSelect.value=state.scenario_id;updateOptions();show(state);
        }catch(error){$('routing-status').textContent=error.message;}finally{$('research-create').disabled=false;}
    });
    $('research-condition').addEventListener('change',()=>control({conditions:$('research-condition').value}));
    $('research-clock').addEventListener('click',()=>control({running:!current?.running}));
    $('research-step').addEventListener('click',()=>control({advance_s:10}));
    $('research-train').addEventListener('click',async()=>{
        const button=$('research-train');button.disabled=true;
        try{
            const run=await api('/api/fl/experiments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
                scenario_id:Number(scenarioSelect.value),task:'network_delay',algorithm:'Predictive',prediction_target:'application_link',
                pool_mode:'all',partition:'non_iid',samples_per_client:2000,online_steps:20,rounds:20,client_count:6,
                local_epochs:2,batch_size:64,learning_rate:.01,seed:42})});
            window.postMessage({type:'sagsin:navigate',href:`/fl.html?experiment_id=${run.id}`},location.origin);
        }catch(error){$('research-state').textContent=error.message;}finally{button.disabled=false;}
    });
    const timer=setInterval(poll,2000);
    window.addEventListener('pagehide',()=>clearInterval(timer));
    return {poll};
}

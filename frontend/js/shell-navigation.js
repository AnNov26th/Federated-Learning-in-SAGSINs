const pages = new Map([
    ['/dashboard.html','Dashboard'], ['/network.html','Network'], ['/participants.html','Participants'],
    ['/fl.html','FL Training'], ['/experiments.html','Experiments'], ['/results.html','Results'],
    ['/','Simulation'], ['/index.html','Simulation']
]);

export function setupShellNavigation({frame, links, onSimulation, onPage}) {
    function resolve(href) {
        try {
            const url = new URL(href, location.href);
            if(url.origin !== location.origin || !pages.has(url.pathname))return null;
            return url;
        } catch {return null;}
    }
    function navigate(href) {
        const url=resolve(href);if(!url)return false;
        const name=pages.get(url.pathname);
        links.forEach(link=>link.classList.toggle('active',link.querySelector('.link-text')?.textContent.trim()===name));
        if(name==='Simulation') {
            frame.style.display='none';frame.removeAttribute('src');onSimulation();
        } else {
            onPage();frame.src=url.pathname+url.search+url.hash;frame.style.display='block';
        }
        return true;
    }
    function intercept(event) {
        if(event.defaultPrevented || event.button!==0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
        const link=event.target.closest?.('a[href]');
        if(!link || link.hasAttribute('download') || link.target==='_blank')return;
        const href=link.getAttribute('href');
        if(!href || href.startsWith('#') || !resolve(link.href))return;
        event.preventDefault();event.stopPropagation();navigate(link.href);
    }
    document.addEventListener('click',intercept,true);
    // Same-origin child pages retain the shell even for target="_top" links.
    frame.addEventListener('load',()=>{
        try{frame.contentDocument?.addEventListener('click',intercept,true);}catch{}
    });
    for(const link of links) {
        const name=link.querySelector('.link-text')?.textContent.trim();
        link.setAttribute('aria-label',name || link.dataset.tooltip);
        const route=[...pages].find(([,value])=>value===name)?.[0];
        if(route)link.href=route;
    }
    window.addEventListener('message',event=>{
        if(event.origin===location.origin && (event.source===window || event.source===frame.contentWindow)
            && event.data?.type==='sagsin:navigate')navigate(event.data.href);
    });
    return {navigate};
}

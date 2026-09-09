(() => {
    const boards = [
        ['agx','Jetson AGX Orin','ARM64 · NVIDIA','边缘 AI 计算','Edge AI compute'],
        ['orin','Jetson Orin','ARM64 · NVIDIA','嵌入式协同推理','Embedded inference'],
        ['meles','Milk-V Meles','RISC-V 64','开放指令集研究','Open-ISA research'],
        ['pi','Raspberry Pi','ARM64','轻量级边缘计算','Lightweight edge compute'],
        ['starfive','VisionFive 2','RISC-V 64','异构系统实验','Heterogeneous systems'],
        ['pioneer','Milk-V Pioneer','RISC-V 64','多核系统研究','Multicore systems'],
        ['jnano','Jetson Nano','ARM64 · NVIDIA','端侧 AI 原型','Device AI prototyping'],
        ['oripi','Orange Pi','ARM64','端侧感知与控制','Sensing and control'],
    ];
    document.querySelectorAll('[data-hardware-gallery]').forEach(root => {
        let selected = 0;
        const zh = () => (window.I18N?.getLang() || 'zh') === 'zh';
        function render() {
            const row = boards[selected];
            root.innerHTML = `<header class="hardware-heading"><div><span>HETEROGENEOUS HARDWARE</span><h2>${zh()?'研究，落在真实设备上。':'Research meets real hardware.'}</h2></div><a href="/devices.html">${zh()?'设备清单':'Device inventory'} <span aria-hidden="true">↗</span></a></header><div class="hardware-stage"><div class="hardware-object"><img src="/assets/boards/${row[0]}.png" alt="${row[1]}" width="800" height="650" loading="lazy" /><span class="hardware-index">${String(selected+1).padStart(2,'0')} / 08</span></div><div class="hardware-spec"><span class="hardware-chip">${row[2]}</span><h3>${row[1]}</h3><p>${row[zh()?3:4]}</p><dl><div><dt>${zh()?'研究平台':'PLATFORM'}</dt><dd>Cloud · Edge · Device</dd></div><div><dt>${zh()?'实验方式':'EXPERIMENTS'}</dt><dd>${zh()?'多智能体协作 / 论文复现':'Multi-agent / Reproduction'}</dd></div></dl><a href="/paper_workspace.html">${zh()?'进入实验工作区':'Open research workspace'} <span aria-hidden="true">↗</span></a><small>${zh()?'设备型号展示，资源可用性以实验调度结果为准。':'Model photography. Availability is verified during scheduling.'}</small></div></div><div class="hardware-thumbnails" role="tablist" aria-label="${zh()?'选择硬件':'Select hardware'}">${boards.map((item,index)=>`<button type="button" role="tab" data-board="${index}" aria-selected="${index===selected}" title="${item[1]}"><img src="/assets/boards/${item[0]}.png" alt="" width="100" height="80" loading="lazy" /><span>${item[1]}</span></button>`).join('')}</div>`;
            root.querySelectorAll('[data-board]').forEach(button => button.onclick = () => {selected=Number(button.dataset.board);render();root.querySelector(`[data-board="${selected}"]`).focus();});
            const object = root.querySelector('.hardware-object');
            object.onpointermove = event => {
                if(matchMedia('(prefers-reduced-motion: reduce)').matches || event.pointerType==='touch')return;
                const box = object.getBoundingClientRect();
                object.querySelector('img').style.transform=`perspective(1000px) rotateY(${((event.clientX-box.x)/box.width-.5)*14}deg) rotateX(${(.5-(event.clientY-box.y)/box.height)*8}deg)`;
            };
            object.onpointerleave=()=>object.querySelector('img').style.transform='none';
        }
        root.addEventListener('keydown',event=>{
            if(!event.target.closest('[data-board]')||!['ArrowLeft','ArrowRight'].includes(event.key))return;
            event.preventDefault();selected=(selected+(event.key==='ArrowRight'?1:boards.length-1))%boards.length;render();root.querySelector(`[data-board="${selected}"]`).focus();
        });
        render();window.I18N?.onChange(render);
    });
})();

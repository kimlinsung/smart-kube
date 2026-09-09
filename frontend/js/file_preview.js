/* Local viewers only: uploaded scripts, HTML and Office macros are never run. */
window.FilePreview = (() => {
    const $=id=>document.getElementById(id),esc=value=>escapeHtml(String(value??''));
    let version=0, pdfTask=null, renderTask=null, previousFocus=null;
    function markdown(text) {
        return window.DOMPurify&&window.marked ? DOMPurify.sanitize(marked.parse(text),{
            FORBID_TAGS:['img','iframe','style','video','audio','form','input'],FORBID_ATTR:['style'],
        }) : '<pre>'+esc(text)+'</pre>';
    }
    function table(rows) {
        const columns=Math.max(0,...rows.map(row=>row.length));
        return `<div class="preview-table"><table><thead><tr><th>#</th>${Array.from({length:columns},(_,i)=>`<th>${i+1}</th>`).join('')}</tr></thead><tbody>${rows.map((row,i)=>`<tr><th>${i+1}</th>${Array.from({length:columns},(_,j)=>`<td>${esc(row[j])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    function cleanup() {
        version++;
        renderTask?.cancel();renderTask=null;
        pdfTask?.destroy().catch(()=>{});pdfTask=null;
        $('filePreview').querySelectorAll('audio,video').forEach(media=>{media.pause();media.removeAttribute('src');media.load();});
    }
    function close() {cleanup();$('filePreviewBackdrop').hidden=true;$('filePreview').replaceChildren();previousFocus?.focus();}
    async function pdf(data, requestVersion) {
        const module=await import('/vendor/pdfjs/build/pdf.min.mjs');
        if(requestVersion!==version)return;
        module.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/build/pdf.worker.min.mjs';
        const task=module.getDocument({url:data.url,withCredentials:true,isEvalSupported:false,
            cMapUrl:'/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/vendor/pdfjs/standard_fonts/',
            wasmUrl:'/vendor/pdfjs/wasm/',iccUrl:'/vendor/pdfjs/iccs/',enableXfa:false});
        pdfTask=task;
        const doc=await task.promise;
        if(requestVersion!==version)return;
        let pageNumber=1,zoom=1,renderVersion=0;
        $('previewToolbar').innerHTML='<button id="pdfPrev" aria-label="上一页" title="上一页"><i data-lucide="chevron-left"></i></button><span id="pdfPageNumber"></span><button id="pdfNext" aria-label="下一页" title="下一页"><i data-lucide="chevron-right"></i></button><label>缩放<input id="pdfZoom" type="range" min="60" max="180" value="100" /></label>';
        window.lucide?.createIcons();
        async function render() {
            const token=++renderVersion;
            renderTask?.cancel();
            try {
                const page=await doc.getPage(pageNumber);
                if(token!==renderVersion||requestVersion!==version)return;
                const natural=page.getViewport({scale:1});
                const width=Math.min(1000,Math.max(200,$('filePreview').clientWidth-48));
                const scale=width/natural.width*zoom,viewport=page.getViewport({scale});
                const ratio=Math.min(devicePixelRatio,2,Math.sqrt(8000000/(viewport.width*viewport.height)));
                const canvas=document.createElement('canvas');canvas.className='preview-pdf-page';
                canvas.width=Math.floor(viewport.width*ratio);canvas.height=Math.floor(viewport.height*ratio);
                canvas.style.width=viewport.width+'px';canvas.style.maxWidth='none';canvas.style.height=viewport.height+'px';
                canvas.setAttribute('aria-label',`PDF 第 ${pageNumber} 页`);
                $('filePreview').replaceChildren(canvas);
                $('pdfPageNumber').textContent=`${pageNumber} / ${doc.numPages}`;
                $('pdfPrev').disabled=pageNumber===1;$('pdfNext').disabled=pageNumber===doc.numPages;
                renderTask=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:[ratio,0,0,ratio,0,0]});
                await renderTask.promise;
            } catch(error) {if(error.name!=='RenderingCancelledException'&&requestVersion===version)$('filePreview').innerHTML='<div class="preview-notice">'+esc(error.message)+'</div>';}
        }
        $('pdfPrev').onclick=()=>{if(pageNumber>1){pageNumber--;render();}};
        $('pdfNext').onclick=()=>{if(pageNumber<doc.numPages){pageNumber++;render();}};
        $('pdfZoom').oninput=event=>{zoom=Number(event.target.value)/100;render();};
        await render();
    }
    async function open(workspaceId,fileId) {
        cleanup();const requestVersion=version;
        previousFocus=document.activeElement;
        $('previewFilename').textContent='加载文件';$('previewMeta').textContent='';$('previewToolbar').replaceChildren();
        $('filePreview').innerHTML='<div class="preview-notice"><span class="spinner"></span></div>';
        $('previewDownload').href=`/api/paper/workspaces/${encodeURIComponent(workspaceId)}/files/${fileId}/download`;
        $('filePreviewBackdrop').hidden=false;$('closePreview').focus();
        try {
            const data=await API.paperFileContent(workspaceId,fileId);
            if(requestVersion!==version)return;
            $('previewFilename').textContent=data.filename;
            const kinds={pdf:'PDF',image:'图像',document:'Word 内容视图',spreadsheet:'数据表格',slides:'幻灯片内容视图',notebook:'Notebook',markdown:'Markdown',json:'JSON',text:'文本 / 代码',video:'视频',audio:'音频',download:'原始文件'};
            $('previewMeta').textContent=(kinds[data.kind]||'文本')+' · '+Math.ceil((data.size||0)/1024)+' KB'+(data.truncated?' · 已截取预览范围':'');
            if(data.kind==='pdf') {await pdf(data,requestVersion);return;}
            if(['image','video','audio'].includes(data.kind)) {
                const element=document.createElement(data.kind==='image'?'img':data.kind);
                element.src=data.url;
                if(data.kind==='image') element.alt=data.filename;else element.controls=true;
                element.onerror=()=>{if(requestVersion===version)$('filePreview').innerHTML='<div class="preview-notice">浏览器无法解码此文件，请下载查看</div>';};
                $('filePreview').replaceChildren(element);return;
            }
            if(data.kind==='spreadsheet') {
                $('previewToolbar').innerHTML='<select id="previewSheet" aria-label="工作表">'+data.sheets.map((sheet,i)=>`<option value="${i}">${esc(sheet.name)}</option>`).join('')+'</select>';
                const draw=index=>{$('filePreview').innerHTML=table(data.sheets[index]?.rows||[]);};
                $('previewSheet').onchange=event=>draw(Number(event.target.value));draw(0);return;
            }
            if(data.kind==='document') {
                $('filePreview').innerHTML='<article class="preview-document">'+data.blocks.map(block=>block.type==='table'?table(block.rows):block.heading?'<h2>'+esc(block.text)+'</h2>':'<p>'+esc(block.text)+'</p>').join('')+'</article>';return;
            }
            if(data.kind==='slides') {
                $('filePreview').innerHTML=data.slides.map((blocks,i)=>`<article class="preview-slide"><small>SLIDE ${String(i+1).padStart(2,'0')}</small>${blocks.map(text=>'<p>'+esc(text).replace(/\n/g,'<br>')+'</p>').join('')}</article>`).join('');return;
            }
            if(data.kind==='notebook') {
                $('filePreview').innerHTML=data.cells.map((cell,i)=>`<section class="preview-cell"><span>[${i+1}]</span><div>${cell.type==='markdown'?'<article class="preview-document">'+markdown(cell.source)+'</article>':'<pre>'+esc(cell.source)+'</pre>'}${cell.output?'<pre class="preview-output">'+esc(cell.output)+'</pre>':''}</div></section>`).join('');return;
            }
            if(data.kind==='download') {$('filePreview').innerHTML='<div class="preview-notice">'+esc(data.content)+'</div>';return;}
            const raw=()=>{$('filePreview').innerHTML='<pre>'+esc(data.content)+'</pre>';};
            if(data.kind==='markdown') {
                $('previewToolbar').innerHTML='<button id="previewRendered" class="active">文档</button><button id="previewSource">源码</button>';
                const rendered=()=>{$('filePreview').innerHTML='<article class="preview-document">'+markdown(data.content)+'</article>';};
                $('previewRendered').onclick=()=>{rendered();$('previewRendered').classList.add('active');$('previewSource').classList.remove('active');};
                $('previewSource').onclick=()=>{raw();$('previewSource').classList.add('active');$('previewRendered').classList.remove('active');};rendered();
            } else raw();
        } catch(error) {
            if(requestVersion!==version)return;
            $('previewMeta').textContent='预览未完成';$('filePreview').innerHTML='<div class="preview-notice">'+esc(error.message)+'</div>';
        }
    }
    $('closePreview').onclick=close;
    $('filePreviewBackdrop').onclick=event=>{if(event.target===event.currentTarget)close();};
    document.addEventListener('keydown',event=>{
        if($('filePreviewBackdrop').hidden)return;
        if(event.key==='Escape'){event.stopPropagation();close();}
        if(event.key==='Tab') {
            const controls=[...$('filePreviewBackdrop').querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select')].filter(element=>element.getClientRects().length);
            const first=controls[0],last=controls[controls.length-1];
            if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
            else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
        }
    });
    return {open,close};
})();

// 统一 API 封装：所有请求带 cookie，401 自动跳登录。
const API = {
    async request(method, url, body, isForm=false) {
        const opts = { method, credentials: 'include', headers: {} };
        if (body) {
            if (isForm) {
                opts.body = body;  // FormData
            } else {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }
        }
        const resp = await fetch(url, opts);
        if (resp.status === 401 && !url.endsWith('/api/me') && !url.endsWith('/api/login')) {
            window.location.href = '/login.html';
            return;
        }
        let data;
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('json')) {
            data = await resp.json();
        } else {
            data = { text: await resp.text() };
        }
        if (!resp.ok) {
            throw new Error(data.error || ('HTTP ' + resp.status));
        }
        return data;
    },
    get(url) { return this.request('GET', url); },
    post(url, body) { return this.request('POST', url, body); },
    del(url) { return this.request('DELETE', url); },
    upload(url, formData) { return this.request('POST', url, formData, true); },

    // ---- 业务封装 ----
    me() { return this.get('/api/me'); },
    login(u, p) { return this.post('/api/login', { username: u, password: p }); },
    logout() { return this.post('/api/logout'); },
    register(u, p) { return this.post('/api/register', { username: u, password: p }); },

    listResources() { return this.get('/api/resources'); },
    deleteResource(name) { return this.del('/api/resources/' + encodeURIComponent(name)); },
    describeResource(name) { return this.get('/api/resources/' + encodeURIComponent(name) + '/describe'); },
    clusterInfo() { return this.get('/api/cluster/info'); },

    chat(msg) { return this.post('/api/chat', { message: msg }); },
    startChatTask(msg) { return this.post('/api/chat/tasks', { message: msg }); },
    chatHistory() { return this.get('/api/chat/history'); },
    clearChat() { return this.del('/api/chat/history'); },
    tasks() { return this.get('/api/tasks'); },

    upload_(file) {
        const fd = new FormData(); fd.append('file', file);
        return this.upload('/api/upload', fd);
    },
    uploadWithProgress(file, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload');
            xhr.withCredentials = true;
            xhr.upload.onprogress = event => {
                if (event.lengthComputable && onProgress) onProgress(Math.round(event.loaded / event.total * 100));
            };
            xhr.onload = () => {
                let data = {};
                try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { data = {}; }
                if (xhr.status === 401) { window.location.href = '/login.html'; return; }
                if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(data.error || ('HTTP ' + xhr.status))); return; }
                resolve(data);
            };
            xhr.onerror = () => reject(new Error('网络连接中断'));
            const form = new FormData(); form.append('file', file);
            xhr.send(form);
        });
    },
    currentScript() { return this.get('/api/scripts/current'); },
    runScript(fileId, options={}) { return this.post(`/api/scripts/${fileId}/run`, options); },
    paperWorkspaces() { return this.get('/api/paper/workspaces'); },
    paperWorkspace(id) { return this.get(`/api/paper/workspaces/${encodeURIComponent(id)}`); },
    createPaperWorkspace(formData, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/paper/workspaces');
            xhr.withCredentials = true;
            xhr.upload.onprogress = event => {
                if (event.lengthComputable && onProgress) onProgress(Math.round(event.loaded / event.total * 100));
            };
            xhr.onload = () => {
                let data = {};
                try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { data = {}; }
                if (xhr.status === 401) { window.location.href = '/login.html'; return; }
                if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(data.error || ('HTTP ' + xhr.status))); return; }
                resolve(data);
            };
            xhr.onerror = () => reject(new Error('网络连接中断'));
            xhr.send(formData);
        });
    },
    paperFileContent(workspaceId, fileId) {
        return this.get(`/api/paper/workspaces/${encodeURIComponent(workspaceId)}/files/${fileId}/content`);
    },
    retryPaperAnalysis(id) { return this.post(`/api/paper/workspaces/${encodeURIComponent(id)}/analysis/retry`); },
    reclaimPaperWorkspace(id) { return this.post(`/api/paper/workspaces/${encodeURIComponent(id)}/reclaim`); },
    uploadToPod(file, podName, destDir='/tmp') {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('pod_name', podName);
        fd.append('dest_dir', destDir);
        return this.upload('/api/upload/to_pod', fd);
    },

    logs(params={}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([key, value]) => {
            if (value !== '' && value != null) qs.set(key, value);
        });
        const query = qs.toString();
        return this.get('/api/logs' + (query ? '?' + query : ''));
    },

    adminNodes() { return this.get('/api/admin/nodes'); },
    adminCordonNode(name) { return this.request('POST', `/api/admin/nodes/${encodeURIComponent(name)}/cordon`); },
    adminUncordonNode(name) { return this.request('POST', `/api/admin/nodes/${encodeURIComponent(name)}/uncordon`); },
    adminDeleteNode(name) { return this.del('/api/admin/nodes/' + encodeURIComponent(name)); },
    adminPods() { return this.get('/api/admin/pods'); },
    adminUsers() { return this.get('/api/admin/users'); },
    adminCreateUser(u, p, role) { return this.post('/api/admin/users', { username: u, password: p, role }); },
    adminChangePassword(id, password) { return this.request('PUT', `/api/admin/users/${id}/password`, { password }); },
    adminSetUserRole(id, role) { return this.request('PUT', `/api/admin/users/${id}/role`, { role }); },
    adminDeleteUser(id) { return this.del('/api/admin/users/' + id); },

    listExperiments() { return this.get('/api/experiments'); },
    getExperiment(id) { return this.get('/api/experiments/' + id); },
    createExperiment(name, description) { return this.post('/api/experiments', { name, description }); },
    enterExperiment(id) { return this.post(`/api/experiments/${id}/enter`); },
    deleteExperiment(id) { return this.del('/api/experiments/' + id); },
    experimentSharing(id) { return this.get(`/api/experiments/${id}/sharing`); },
    addExperimentCollaborator(id, username) {
        return this.post(`/api/experiments/${id}/collaborators`, { username });
    },
    removeExperimentCollaborator(id, userId) {
        return this.del(`/api/experiments/${id}/collaborators/${userId}`);
    },
    enableExperimentShare(id) { return this.post(`/api/experiments/${id}/share`); },
    disableExperimentShare(id) { return this.del(`/api/experiments/${id}/share`); },
    sharedExperiment(token) {
        return this.get(`/api/public/experiments/shared/${encodeURIComponent(token)}`);
    },
};

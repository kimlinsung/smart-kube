export async function openAccountSecurity(target = null) {
    if (document.querySelector('.security-dialog')) return;
    const trigger = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.className = 'console-dialog security-dialog';
    dialog.setAttribute('aria-labelledby', 'securityTitle');
    dialog.innerHTML = `<header><div><span class="dialog-eyebrow">ACCOUNT SECURITY</span><h2 id="securityTitle">账户安全</h2></div><button type="button" data-close aria-label="关闭" title="关闭">×</button></header><form class="dialog-content"><p class="dialog-error" role="alert"></p><p class="security-status">正在验证账户…</p><label data-current>当前密码<input name="current_password" type="password" autocomplete="current-password" maxlength="128" /></label><a data-reauth href="/api/feishu/login?next=%2Fdashboard.html%3Fsecurity%3D1" hidden>通过飞书重新验证身份</a><label>新密码<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required /></label><p class="password-requirements">12–128 位，包含大小写字母、数字和符号，不含空白、用户名或常见密码。</p><label>确认新密码<input name="confirm" type="password" autocomplete="new-password" minlength="12" maxlength="128" required /></label><footer><button type="button" data-close>取消</button><button type="submit" class="primary" disabled>更新密码</button></footer></form>`;
    document.body.appendChild(dialog); dialog.showModal();
    const $ = selector => dialog.querySelector(selector);
    dialog.querySelectorAll('[data-close]').forEach(button => button.onclick = () => dialog.close());
    dialog.onclose = () => { dialog.remove(); trigger?.focus(); };
    try {
        const user = await API.me();
        if (target && user.role !== 'admin') throw new Error('需要管理员权限');
        $('[data-current]').hidden = !!target || !!user.can_reset_with_feishu;
        $('[name=current_password]').required = !target && !user.can_reset_with_feishu;
        $('[data-reauth]').hidden = !!target || !user.feishu_open_id;
        if (target) $('#securityTitle').textContent = '重置用户密码';
        $('.security-status').textContent = target ? `将重置 ${target.name} 的密码并使其已有登录会话失效。` : user.can_reset_with_feishu ? '飞书身份已验证。本次修改后，其他已有登录会话将失效。' : user.password_generated ? '当前使用系统生成的随机凭据。修改前请通过飞书验证身份。' : '修改密码后，其他已有登录会话将失效。';
        $('[type=submit]').disabled = false;
    } catch (err) { $('.dialog-error').textContent = err.message; }
    $('form').onsubmit = async event => {
        event.preventDefault(); const password = $('[name=password]').value;
        if (password !== $('[name=confirm]').value) { $('.dialog-error').textContent = '两次输入的密码不一致'; return; }
        $('[type=submit]').disabled = true; $('.dialog-error').textContent = '';
        try {
            if (target) await API.adminChangePassword(target.id, password);
            else await API.changeOwnPassword(password, $('[name=current_password]').value);
            $('form').reset(); $('.security-status').textContent = '密码已更新。';
            dialog.close();
            alert('密码已更新。');
        } catch (err) { $('.dialog-error').textContent = err.message; }
        finally { $('[type=submit]').disabled = false; }
    };
}

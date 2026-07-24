(() => {
    'use strict';

    const data = window.GitHubUploadData || {};
    const state = { source: 'folder', files: [], repositories: [], branches: [] };
    const $ = (selector, context = document) => context.querySelector(selector);
    const $$ = (selector, context = document) => Array.from(context.querySelectorAll(selector));

    const els = {
        notice: $('#githubupload-notice'),
        folderInput: $('#githubupload-folder-input'),
        zipInput: $('#githubupload-zip-input'),
        folderZone: $('#githubupload-folder-zone'),
        zipZone: $('#githubupload-zip-zone'),
        preview: $('#githubupload-file-preview'),
        fileList: $('#githubupload-file-list'),
        summary: $('#githubupload-selection-summary'),
        clearSelection: $('#githubupload-clear-selection'),
        start: $('#githubupload-start'),
        progress: $('#githubupload-progress'),
        progressBar: $('#githubupload-progress-bar'),
        progressLabel: $('#githubupload-progress-label'),
        progressPercent: $('#githubupload-progress-percent'),
    };

    function initTabs() {
        $$('.githubupload-tabs button').forEach((button) => {
            button.addEventListener('click', () => openTab(button.dataset.tab));
        });
    }

    function openTab(tab) {
        $$('.githubupload-tabs button').forEach((button) => button.classList.toggle('is-active', button.dataset.tab === tab));
        $$('.githubupload-tab').forEach((panel) => panel.classList.toggle('is-active', panel.dataset.panel === tab));
    }

    function initSourceSwitch() {
        $$('input[name="githubupload_source"]').forEach((input) => {
            input.addEventListener('change', () => {
                state.source = input.value;
                $$('.githubupload-source-switch label').forEach((label) => label.classList.toggle('is-active', label.contains(input)));
                if (els.folderZone) els.folderZone.hidden = state.source !== 'folder';
                if (els.zipZone) els.zipZone.hidden = state.source !== 'zip';
                clearSelection();
            });
        });

        els.folderInput?.addEventListener('change', () => selectFiles(Array.from(els.folderInput.files || [])));
        els.zipInput?.addEventListener('change', () => selectFiles(Array.from(els.zipInput.files || [])));
        els.clearSelection?.addEventListener('click', clearSelection);
    }

    function selectFiles(files) {
        state.files = files;
        const count = files.length;
        const bytes = files.reduce((sum, file) => sum + Number(file.size || 0), 0);
        const largest = files.reduce((max, file) => Math.max(max, Number(file.size || 0)), 0);

        if (count > Number(data.maxFiles || 500)) {
            showNotice(data.strings?.tooManyFiles || 'Too many files.', 'error');
        } else if (bytes > Number(data.maxBytes || 0)) {
            showNotice(data.strings?.tooLarge || 'The selected files are too large.', 'error');
        } else if (largest > Number(data.maxSingleBytes || 0)) {
            showNotice(data.strings?.singleTooLarge || 'A selected file is too large.', 'error');
        }

        if (els.summary) {
            els.summary.textContent = count ? `${formatNumber(count)} file${count === 1 ? '' : 's'} · ${formatBytes(bytes)} · ~${formatNumber(count + 5)} API calls` : 'Nothing selected';
            els.summary.classList.toggle('is-success', count > 0);
        }
        if (els.preview) els.preview.hidden = count === 0;
        renderPreview(files);
    }

    function renderPreview(files) {
        if (!els.fileList) return;
        els.fileList.innerHTML = '';
        files.slice(0, 150).forEach((file) => {
            const row = document.createElement('div');
            row.className = 'githubupload-file-row';
            row.innerHTML = '<span class="dashicons dashicons-media-default"></span><code></code><small></small>';
            $('code', row).textContent = file.webkitRelativePath || file.name;
            $('small', row).textContent = formatBytes(file.size || 0);
            els.fileList.appendChild(row);
        });
        if (files.length > 150) {
            const more = document.createElement('div');
            more.className = 'githubupload-file-more';
            more.textContent = `+ ${formatNumber(files.length - 150)} more files`;
            els.fileList.appendChild(more);
        }
    }

    function clearSelection() {
        state.files = [];
        if (els.folderInput) els.folderInput.value = '';
        if (els.zipInput) els.zipInput.value = '';
        if (els.preview) els.preview.hidden = true;
        if (els.fileList) els.fileList.innerHTML = '';
        if (els.summary) {
            els.summary.textContent = 'Nothing selected';
            els.summary.classList.remove('is-success');
        }
    }

    function initSettings() {
        $('#githubupload-toggle-token')?.addEventListener('click', (event) => {
            const input = $('#githubupload-token');
            if (!input) return;
            const showing = input.type === 'text';
            input.type = showing ? 'password' : 'text';
            event.currentTarget.textContent = showing ? 'Show' : 'Hide';
        });

        ['#githubupload-save-settings', '#githubupload-save-security'].forEach((selector) => {
            $(selector)?.addEventListener('click', saveSettings);
        });

        $('#githubupload-test')?.addEventListener('click', testConnection);
        $('#githubupload-load-repositories')?.addEventListener('click', loadRepositories);
        $('#githubupload-load-repositories-upload')?.addEventListener('click', loadRepositories);
        $('#githubupload-load-branches')?.addEventListener('click', loadBranches);
        $('#githubupload-load-branches-upload')?.addEventListener('click', loadBranches);

        [
            ['#githubupload-settings-repository', '#githubupload-repository'],
            ['#githubupload-settings-branch', '#githubupload-branch'],
            ['#githubupload-settings-target', '#githubupload-target-path'],
            ['#githubupload-repository', '#githubupload-settings-repository'],
            ['#githubupload-branch', '#githubupload-settings-branch'],
            ['#githubupload-target-path', '#githubupload-settings-target'],
        ].forEach(([from, to]) => {
            $(from)?.addEventListener('input', () => { if ($(to)) $(to).value = $(from).value; });
        });

        $('#githubupload-clear-history')?.addEventListener('click', async (event) => {
            if (!window.confirm(data.strings?.confirmClear || 'Clear history?')) return;
            setBusy(event.currentTarget, true, 'Clearing…');
            try {
                await postForm('githubupload_clear_history', new FormData());
                const wrap = $('#githubupload-history-wrap');
                if (wrap) wrap.innerHTML = '<div class="githubupload-empty-state"><span class="dashicons dashicons-backup"></span><h3>No uploads yet</h3><p>New upload activity will appear here.</p></div>';
                event.currentTarget.remove();
                showNotice('History cleared.', 'success');
            } catch (error) {
                showNotice(error.message, 'error');
                setBusy(event.currentTarget, false);
            }
        });
    }

    async function saveSettings(event) {
        setBusy(event.currentTarget, true, 'Saving…');
        try {
            const response = await postForm('githubupload_save_settings', settingsPayload());
            showNotice(response.data.message || data.strings?.saved || 'Settings saved.', 'success');
            syncDestinationFields();
            data.maxBytes = response.data.maxBytes || data.maxBytes;
            data.maxSingleBytes = response.data.maxSingleBytes || data.maxSingleBytes;
            const badge = $('#githubupload-token-status');
            if (badge) {
                badge.textContent = response.data.hasSavedToken ? 'Token configured' : 'Token required';
                badge.classList.toggle('is-success', Boolean(response.data.hasSavedToken));
            }
        } catch (error) {
            showNotice(error.message, 'error');
        } finally {
            setBusy(event.currentTarget, false);
        }
    }

    async function testConnection(event) {
        const panel = $('#githubupload-diagnostics');
        const grid = $('#githubupload-diagnostics-grid');
        setBusy(event.currentTarget, true, 'Testing API…');
        if (panel) panel.hidden = true;
        try {
            const response = await postForm('githubupload_test_connection', settingsPayload());
            if (panel && grid) {
                panel.hidden = false;
                renderDiagnostics(grid, response.data);
            }
            showNotice(response.data.message, 'success');
        } catch (error) {
            showNotice(error.message, 'error');
        } finally {
            setBusy(event.currentTarget, false);
        }
    }

    async function loadRepositories(event) {
        setBusy(event.currentTarget, true, 'Loading…');
        const result = $('#githubupload-repository-result');
        try {
            const response = await postForm('githubupload_discover_repositories', settingsPayload());
            state.repositories = response.data.repositories || [];
            const list = $('#githubupload-repository-list');
            if (list) {
                list.innerHTML = '';
                state.repositories.forEach((repo) => {
                    const option = document.createElement('option');
                    option.value = repo.fullName;
                    option.label = `${repo.private ? 'Private' : 'Public'}${repo.canPush === false ? ' · read only' : ''}${repo.archived ? ' · archived' : ''}`;
                    list.appendChild(option);
                });
            }
            if (result) {
                result.hidden = false;
                result.className = 'githubupload-inline-result is-success';
                result.textContent = response.data.message || `${state.repositories.length} repositories loaded.`;
            }
            if (!state.repositories.length) showNotice(data.strings?.noRepositories || 'No repositories returned.', 'error');
        } catch (error) {
            if (result) {
                result.hidden = false;
                result.className = 'githubupload-inline-result is-error';
                result.textContent = error.message;
            }
            showNotice(error.message, 'error');
        } finally {
            setBusy(event.currentTarget, false);
        }
    }

    async function loadBranches(event) {
        const repository = currentRepository();
        if (!repository) {
            showNotice(data.strings?.repositoryRequired || 'Enter a repository first.', 'error');
            return;
        }
        setBusy(event.currentTarget, true, 'Loading…');
        const payload = settingsPayload();
        payload.set('repository', repository);
        try {
            const response = await postForm('githubupload_discover_branches', payload);
            state.branches = response.data.branches || [];
            const list = $('#githubupload-branch-list');
            if (list) {
                list.innerHTML = '';
                state.branches.forEach((branch) => {
                    const option = document.createElement('option');
                    option.value = branch.name;
                    option.label = branch.protected ? 'Protected branch' : 'Branch';
                    list.appendChild(option);
                });
            }
            showNotice(response.data.message || `${state.branches.length} branches loaded.`, state.branches.length ? 'success' : 'error');
        } catch (error) {
            showNotice(error.message, 'error');
        } finally {
            setBusy(event.currentTarget, false);
        }
    }

    function settingsPayload() {
        const form = new FormData();
        append(form, 'token', value('#githubupload-token'));
        append(form, 'clear_token', checked('#githubupload-clear-token'));
        append(form, 'api_root', value('#githubupload-api-root'));
        append(form, 'api_version', value('#githubupload-api-version', '2026-03-10'));
        append(form, 'request_timeout', value('#githubupload-request-timeout', '90'));
        append(form, 'retry_attempts', value('#githubupload-retry-attempts', '1'));
        append(form, 'sslverify', checked('#githubupload-sslverify'));
        append(form, 'repository_visibility', value('#githubupload-repository-visibility', 'all'));
        append(form, 'repository', currentRepository());
        append(form, 'branch', currentBranch());
        append(form, 'target_path', value('#githubupload-settings-target') || value('#githubupload-target-path'));
        append(form, 'create_branch', checked('#githubupload-create-branch'));
        append(form, 'strip_root_folder', checked('#githubupload-strip-root'));
        append(form, 'zip_mode', $('input[name="githubupload_zip_mode"]:checked')?.value || 'extract');
        append(form, 'default_commit_message', value('#githubupload-default-message'));
        append(form, 'commit_author_name', value('#githubupload-author-name'));
        append(form, 'commit_author_email', value('#githubupload-author-email'));
        append(form, 'exclude_patterns', value('#githubupload-excludes'));
        append(form, 'protect_sensitive_files', checked('#githubupload-protect-sensitive'));
        append(form, 'sensitive_patterns', value('#githubupload-sensitive-patterns'));
        append(form, 'allow_workflow_files', checked('#githubupload-allow-workflows'));
        append(form, 'max_total_mb', value('#githubupload-max-total', '100'));
        append(form, 'max_single_mb', value('#githubupload-max-single', '95'));
        append(form, 'delete_on_uninstall', checked('#githubupload-delete-data'));
        return form;
    }

    function currentRepository() {
        return (value('#githubupload-repository') || value('#githubupload-settings-repository')).trim();
    }

    function currentBranch() {
        return (value('#githubupload-branch') || value('#githubupload-settings-branch', 'main')).trim();
    }

    function syncDestinationFields() {
        const pairs = [
            ['#githubupload-settings-repository', '#githubupload-repository'],
            ['#githubupload-settings-branch', '#githubupload-branch'],
            ['#githubupload-settings-target', '#githubupload-target-path'],
        ];
        pairs.forEach(([from, to]) => {
            if ($(from) && $(to)) $(to).value = $(from).value;
        });
    }

    function renderDiagnostics(grid, details) {
        grid.innerHTML = '';
        const reset = details.rateLimit?.reset ? new Date(details.rateLimit.reset * 1000).toLocaleString() : 'Not reported';
        const entries = [
            ['Account', details.login ? `@${details.login}` : 'Connected'],
            ['Repository', details.repository || 'Not selected'],
            ['Push access', details.canPush === null ? 'Not reported' : details.canPush ? 'Allowed' : 'Read only'],
            ['Default branch', details.defaultBranch || 'Not reported'],
            ['Selected branch', details.branchExists ? `${details.branch} exists` : `${details.branch} can be created`],
            ['Visibility', details.private ? 'Private' : 'Public'],
            ['API endpoint', details.apiRoot || ''],
            ['API version', details.apiVersion || ''],
            ['Rate remaining', details.rateLimit ? `${details.rateLimit.remaining} of ${details.rateLimit.limit}` : 'Not reported'],
            ['Rate reset', reset],
            ['Request ID', details.requestId || 'Not reported'],
        ];
        entries.forEach(([label, valueText]) => {
            const item = document.createElement('div');
            item.innerHTML = '<small></small><strong></strong>';
            $('small', item).textContent = label;
            $('strong', item).textContent = valueText;
            grid.appendChild(item);
        });
    }

    function initUpload() {
        els.start?.addEventListener('click', () => {
            if (!state.files.length) {
                showNotice(data.strings?.chooseFiles || 'Choose files first.', 'error');
                return;
            }
            const repository = value('#githubupload-repository').trim();
            const branch = value('#githubupload-branch').trim();
            if (!repository || !branch) {
                showNotice('Repository and branch are required.', 'error');
                return;
            }

            const form = settingsPayload();
            form.append('action', 'githubupload_upload');
            form.append('nonce', data.nonce || '');
            form.set('source_type', state.source);
            form.set('repository', repository);
            form.set('branch', branch);
            form.set('target_path', value('#githubupload-target-path'));
            form.set('commit_message', value('#githubupload-commit-message'));

            state.files.forEach((file) => {
                form.append('files[]', file, file.name);
                form.append('file_paths[]', file.webkitRelativePath || file.name);
            });
            upload(form);
        });
    }

    function upload(form) {
        const xhr = new XMLHttpRequest();
        setBusy(els.start, true, 'Uploading…');
        showProgress(0, data.strings?.uploading || 'Uploading files to WordPress…');
        hideNotice();

        xhr.upload.addEventListener('progress', (event) => {
            if (!event.lengthComputable) return;
            showProgress(Math.min(72, Math.round((event.loaded / event.total) * 72)), data.strings?.uploading || 'Uploading files to WordPress…');
        });
        xhr.upload.addEventListener('load', () => showProgress(80, data.strings?.committing || 'Creating GitHub commit…'));
        xhr.addEventListener('load', () => {
            let response;
            try { response = JSON.parse(xhr.responseText || '{}'); }
            catch (error) { finishUploadError(data.strings?.serverError || 'Invalid server response.'); return; }

            if (xhr.status >= 200 && xhr.status < 300 && response.success) {
                showProgress(100, 'Commit complete.');
                const link = response.data.commitUrl ? ` <a href="${escapeAttribute(response.data.commitUrl)}" target="_blank" rel="noopener noreferrer">View commit</a>` : '';
                showNotice(`${escapeHtml(response.data.message || 'Upload complete.')}${link}`, 'success', true);
                clearSelection();
                setTimeout(() => { if (els.progress) els.progress.hidden = true; }, 1800);
            } else {
                finishUploadError(response?.data?.message || data.strings?.serverError || 'Upload failed.');
            }
            setBusy(els.start, false);
        });
        xhr.addEventListener('error', () => { finishUploadError(data.strings?.serverError || 'Network error.'); setBusy(els.start, false); });
        xhr.addEventListener('abort', () => { finishUploadError('Upload cancelled.'); setBusy(els.start, false); });
        xhr.open('POST', data.ajaxUrl, true);
        xhr.send(form);
    }

    function finishUploadError(message) {
        showProgress(100, 'Upload failed.');
        els.progress?.classList.add('is-error');
        showNotice(message, 'error');
    }

    async function postForm(action, form) {
        form.append('action', action);
        form.append('nonce', data.nonce || '');
        const response = await fetch(data.ajaxUrl, { method: 'POST', body: form, credentials: 'same-origin' });
        let payload;
        try { payload = await response.json(); }
        catch (error) { throw new Error(data.strings?.serverError || 'Invalid server response.'); }
        if (!response.ok || !payload.success) throw new Error(payload?.data?.message || data.strings?.serverError || 'Request failed.');
        return payload;
    }

    function append(form, key, valueText) { form.append(key, valueText ?? ''); }
    function value(selector, fallback = '') { return $(selector)?.value ?? fallback; }
    function checked(selector) { return $(selector)?.checked ? '1' : ''; }

    function setBusy(button, busy, label = '') {
        if (!button) return;
        if (busy) {
            button.dataset.originalHtml = button.innerHTML;
            button.disabled = true;
            button.classList.add('is-busy');
            button.textContent = label || 'Working…';
        } else {
            button.disabled = false;
            button.classList.remove('is-busy');
            if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
        }
    }

    function showProgress(percent, label) {
        if (!els.progress) return;
        els.progress.hidden = false;
        els.progress.classList.remove('is-error');
        els.progressBar.value = percent;
        els.progressPercent.textContent = `${percent}%`;
        els.progressLabel.textContent = label;
    }

    function showNotice(message, type = 'info', html = false) {
        if (!els.notice) return;
        els.notice.hidden = false;
        els.notice.className = `githubupload-notice is-${type}`;
        if (html) els.notice.innerHTML = message;
        else els.notice.textContent = message;
        els.notice.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function hideNotice() { if (els.notice) els.notice.hidden = true; }
    function formatBytes(bytes) {
        const valueNum = Number(bytes || 0);
        if (valueNum < 1024) return `${valueNum} B`;
        const units = ['KB', 'MB', 'GB'];
        let size = valueNum / 1024;
        let index = 0;
        while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
        return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[index]}`;
    }
    function formatNumber(number) { return new Intl.NumberFormat().format(number); }
    function escapeHtml(input) { const node = document.createElement('div'); node.textContent = String(input); return node.innerHTML; }
    function escapeAttribute(input) { return String(input).replace(/["'<>`]/g, ''); }

    initTabs();
    initSourceSwitch();
    initSettings();
    initUpload();
})();

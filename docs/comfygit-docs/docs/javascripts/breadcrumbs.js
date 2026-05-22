// Custom breadcrumbs for pages with a meaningful guide parent.
(function() {
  'use strict';

  const GUIDE_BREADCRUMBS = {
    'user-guide/environments/running-comfyui.md': {
      label: 'Environment Lifecycle',
      href: 'user-guide/environments/'
    },
    'user-guide/environments/sync-and-repair.md': {
      label: 'Environment Lifecycle',
      href: 'user-guide/environments/'
    },
    'user-guide/environments/local-runtime-config.md': {
      label: 'Environment Lifecycle',
      href: 'user-guide/environments/'
    },
    'user-guide/environments/version-control.md': {
      label: 'Environment Lifecycle',
      href: 'user-guide/environments/'
    },
    'user-guide/custom-nodes/development-nodes.md': {
      label: 'Custom Node Management',
      href: 'user-guide/custom-nodes/'
    },
    'user-guide/custom-nodes/managing-nodes.md': {
      label: 'Custom Node Management',
      href: 'user-guide/custom-nodes/'
    },
    'user-guide/custom-nodes/node-conflicts.md': {
      label: 'Custom Node Management',
      href: 'user-guide/custom-nodes/'
    },
    'user-guide/models/model-index.md': {
      label: 'Model Management',
      href: 'user-guide/models/'
    },
    'user-guide/models/downloading-models.md': {
      label: 'Model Management',
      href: 'user-guide/models/'
    },
    'user-guide/models/managing-models.md': {
      label: 'Model Management',
      href: 'user-guide/models/'
    },
    'user-guide/models/adding-sources.md': {
      label: 'Model Management',
      href: 'user-guide/models/'
    },
    'user-guide/workflows/workflow-resolution.md': {
      label: 'Workflow Management',
      href: 'user-guide/workflows/'
    },
    'user-guide/workflows/workflow-contracts.md': {
      label: 'Workflow Management',
      href: 'user-guide/workflows/'
    },
    'user-guide/serve-studio/uploads.md': {
      label: 'Serve And Studio',
      href: 'user-guide/serve-studio/'
    },
    'user-guide/python-dependencies/py-commands.md': {
      label: 'Python Dependencies',
      href: 'user-guide/python-dependencies/'
    },
    'user-guide/python-dependencies/constraints.md': {
      label: 'Python Dependencies',
      href: 'user-guide/python-dependencies/'
    },
    'user-guide/collaboration/export-import.md': {
      label: 'Sharing And Collaboration',
      href: 'user-guide/collaboration/'
    },
    'user-guide/collaboration/git-remotes.md': {
      label: 'Sharing And Collaboration',
      href: 'user-guide/collaboration/'
    },
    'user-guide/collaboration/materialize.md': {
      label: 'Sharing And Collaboration',
      href: 'user-guide/collaboration/'
    }
  };

  function getCurrentPagePath() {
    let path = window.location.pathname
      .replace(/^\/+|\/+$/g, '')
      .replace(/\/index\.html$/, '');

    if (!path || path === 'index.html') {
      return 'index.md';
    }

    return path.endsWith('.md') ? path : path + '.md';
  }

  function getSiteUrl(path) {
    const root = typeof __md_scope !== 'undefined'
      ? __md_scope
      : new URL('/', window.location.href);

    return new URL(path.replace(/^\/+/, ''), root).pathname;
  }

  function removeBreadcrumbs() {
    document.querySelectorAll('.cg-breadcrumbs').forEach((element) => element.remove());
  }

  function createBreadcrumb(parent) {
    const nav = document.createElement('nav');
    nav.className = 'md-path cg-breadcrumbs';
    nav.setAttribute('aria-label', 'Breadcrumb');

    const list = document.createElement('ol');
    list.className = 'md-path__list';

    const item = document.createElement('li');
    item.className = 'md-path__item';

    const link = document.createElement('a');
    link.className = 'md-path__link';
    link.href = getSiteUrl(parent.href);
    link.textContent = parent.label;

    item.appendChild(link);
    list.appendChild(item);
    nav.appendChild(list);

    return nav;
  }

  function injectBreadcrumbs() {
    removeBreadcrumbs();

    const parent = GUIDE_BREADCRUMBS[getCurrentPagePath()];
    if (!parent) {
      return;
    }

    const content = document.querySelector('.md-content');
    const article = content && content.querySelector('.md-content__inner');
    if (!content || !article) {
      return;
    }

    content.insertBefore(createBreadcrumb(parent), article);
  }

  function init() {
    injectBreadcrumbs();
  }

  if (typeof document$ !== 'undefined') {
    document$.subscribe(init);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

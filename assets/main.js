// ── CONSTELLATION ──
(function () {
    var c = document.getElementById('constellation');
    if (!c) return;
    var ctx = c.getContext('2d');
    var W, H, pts = [];
    var mouse = { x: -1000, y: -1000 };

    function resize() { W = c.width = window.innerWidth; H = c.height = window.innerHeight }
    resize();
    window.addEventListener('resize', function () { resize(); init() });
    window.addEventListener('mousemove', function (e) { mouse.x = e.clientX; mouse.y = e.clientY; });
    window.addEventListener('mouseout', function () { mouse.x = -1000; mouse.y = -1000; });

    function init() {
        pts = [];
        var n = Math.floor((W * H) / 10000);
        for (var i = 0; i < n; i++) {
            pts.push({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .35, vy: (Math.random() - .5) * .35, r: Math.random() * 2 + .8 });
        }
    }
    init();
    function draw() {
        ctx.clearRect(0, 0, W, H);
        // Draw connections
        for (var i = 0; i < pts.length; i++) {
            for (var j = i + 1; j < pts.length; j++) {
                var dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
                var d = Math.sqrt(dx * dx + dy * dy);
                if (d < 140) {
                    ctx.beginPath();
                    ctx.strokeStyle = 'rgba(0,212,255,' + (0.25 * (1 - d / 140)) + ')';
                    ctx.lineWidth = .6;
                    ctx.moveTo(pts[i].x, pts[i].y);
                    ctx.lineTo(pts[j].x, pts[j].y);
                    ctx.stroke();
                }
            }

            // Mouse interaction connection
            var mdx = pts[i].x - mouse.x, mdy = pts[i].y - mouse.y;
            var md = Math.sqrt(mdx * mdx + mdy * mdy);
            if (md < 180) {
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(124,58,237,' + (0.8 * (1 - md / 180)) + ')';
                ctx.lineWidth = 1.2;
                ctx.moveTo(pts[i].x, pts[i].y);
                ctx.lineTo(mouse.x, mouse.y);
                ctx.stroke();
            }
        }
        // Draw dots
        for (var i = 0; i < pts.length; i++) {
            var p = pts[i];
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);

            // Highlight dots near mouse
            var mdx = p.x - mouse.x, mdy = p.y - mouse.y;
            var md = Math.sqrt(mdx * mdx + mdy * mdy);
            if (md < 120) {
                ctx.fillStyle = 'rgba(0,212,255, 1)';
                ctx.shadowColor = 'rgba(0,212,255, 1)';
                ctx.shadowBlur = 10;
            } else {
                ctx.fillStyle = 'rgba(0,212,255,.75)';
                ctx.shadowBlur = 0;
            }
            ctx.fill();

            p.x += p.vx; p.y += p.vy;
            if (p.x < 0 || p.x > W) p.vx *= -1;
            if (p.y < 0 || p.y > H) p.vy *= -1;
        }
        requestAnimationFrame(draw);
    }
    draw();
})();

// ── NAV SCROLL + ACTIVE ──
(function () {
    var nav = document.getElementById('nav');
    window.addEventListener('scroll', function () {
        if (!nav) return;
        nav.classList.toggle('sc', window.scrollY > 50);
        // Active link
        var secs = ['hero', 'about', 'features', 'themes', 'timeline', 'prizes', 'leaderboard', 'coordinators', 'contact'];
        var cur = 'hero';
        secs.forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.getBoundingClientRect().top <= 100) cur = id;
        });
        document.querySelectorAll('.nlinks a').forEach(function (a) {
            a.classList.toggle('active', a.getAttribute('href') === '#' + cur);
        });
    });
})();

// ── HAMBURGER ──
if (document.getElementById('hbg')) {
    document.getElementById('hbg').addEventListener('click', function () {
        var mob = document.getElementById('mob');
        if (mob) mob.classList.toggle('open');
    });
}

function closeMob() {
    var mob = document.getElementById('mob');
    if (mob) mob.classList.remove('open');
}

function toggleFaq(btn) {
    var item = btn.closest('.faq-item');
    var isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item.open').forEach(function (el) { el.classList.remove('open'); });
    if (!isOpen) item.classList.add('open');
}

// ── SCROLL REVEAL ──
var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e, i) {
        if (e.isIntersecting) {
            setTimeout(function () { e.target.classList.add('on') }, i * 70);
            io.unobserve(e.target);
        }
    });
}, { threshold: .1 });
document.querySelectorAll('.rv').forEach(function (el) { io.observe(el) });

// ── PARTICLES ──
(function () {
    var colors = ['#00d4ff', '#b44dff', '#00fff7', '#7c3aed'];
    var particleCount = 18;
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < particleCount; i++) {
        var p = document.createElement('div');
        var s = Math.random() * 2.5 + .8;
        p.style.cssText = 'position:fixed;border-radius:50%;pointer-events:none;z-index:0;width:' + s + 'px;height:' + s + 'px;left:' + Math.random() * 100 + '%;bottom:' + Math.random() * 10 + '%;background:' + colors[Math.floor(Math.random() * colors.length)] + ';box-shadow:0 0 ' + (s * 4) + 'px ' + colors[Math.floor(Math.random() * colors.length)] + ';animation:ptcl ' + (10 + Math.random() * 18) + 's ' + (Math.random() * 10) + 's linear infinite;opacity:' + (0.35 + Math.random() * 0.45) + ';';
        fragment.appendChild(p);
    }
    document.body.appendChild(fragment);
    var st = document.createElement('style');
    st.textContent = '@keyframes ptcl{0%{transform:translateY(0) scale(1);opacity:.8}100%{transform:translateY(-105vh) scale(.2);opacity:0}}';
    document.head.appendChild(st);
})();

// ── COUNTDOWN TIMER ──
(function () {
    const targetDate = new Date("April 17, 2026 08:30:00").getTime();

    function updateCountdown() {
        const now = new Date().getTime();
        const distance = targetDate - now;

        function fmt(n) { return n < 10 ? '0' + Math.max(0, n) : Math.max(0, n); }

        if (distance < 0) {
            document.querySelectorAll('.cd-num').forEach(e => e.innerText = "00");
            return;
        }

        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((distance % (1000 * 60)) / 1000);

        var cd = document.getElementById('cd-d'), ch = document.getElementById('cd-h'), cm = document.getElementById('cd-m'), cs = document.getElementById('cd-s');
        if (cd) cd.textContent = fmt(days);
        if (ch) ch.textContent = fmt(hours);
        if (cm) cm.textContent = fmt(minutes);
        if (cs) cs.textContent = fmt(seconds);
    }

    setInterval(updateCountdown, 1000);
    updateCountdown();
})();

// ── LEADERBOARD ──
function fetchLeaderboard() {
    fetch('/api/projects')
        .then(res => res.json())
        .then(data => {
            const body = document.getElementById('lb-body');
            if (!body) return;
            if (data.length === 0) {
                body.innerHTML = '<tr><td colspan="4" style="padding: 40px; text-align: center; color: var(--dim);">No projects submitted yet. Be the first!</td></tr>';
                return;
            }
            body.innerHTML = data.slice(0, 10).map((p, i) => `
        <tr style="border-bottom: 1px solid rgba(255,255,255,.05); transition: background .3s;" onmouseover="this.style.background='rgba(0,212,255,.03)'" onmouseout="this.style.background='transparent'">
          <td style="padding: 15px 18px; font-weight: 700; color: ${i < 3 ? 'var(--cyan)' : '#fff'};">#${i + 1}</td>
          <td style="padding: 15px 18px;">
            <div style="font-weight: 600;">${p.team_name}</div>
            <div style="font-size: 11px; color: var(--dim);">${p.college}</div>
          </td>
          <td style="padding: 15px 18px;">
            <div style="font-weight: 500; color: var(--pink);">${p.project_title}</div>
            <div style="font-size: 11px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 250px;">${p.project_desc}</div>
          </td>
          <td style="padding: 15px 18px; text-align: right; font-family: 'Orbitron', monospace; color: var(--cyan); font-weight: 700;">${p.upvotes}</td>
        </tr>
      `).join('');
        })
        .catch(err => {
            console.error('Leaderboard error:', err);
            const body = document.getElementById('lb-body');
            if (body) body.innerHTML = '<tr><td colspan="4" style="padding: 40px; text-align: center; color: #ff2d78;">Failed to load leaderboard.</td></tr>';
        });
}

(function () {
    fetchLeaderboard();
})();


// ── REALTIME UPDATES (Socket.IO) ──
(function () {
    if (typeof io === 'undefined') return;
    const socket = io();

    // Announcement Handler
    socket.on('new_announcement', function (ann) {
        showToast(ann.message, 'info');
    });

    // Leaderboard Update Handler
    socket.on('leaderboard_update', function () {
        console.log('Realtime Leaderboard Update Received');
        fetchLeaderboard();
    });

    // Feed Update Handler (Toast)
    socket.on('feed_update', function (data) {
        showToast(data.message, data.type);
    });

    function showToast(msg, type = 'info') {
        var container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        var toast = document.createElement('div');
        toast.className = 'toast ' + (type || 'info');
        var tHtml = `
      <div class="toast-header">
        <span>🔴 ${type === 'success' ? 'SUCCESS' : type === 'warning' ? 'WARNING' : 'LIVE UPDATE'}</span>
        <span class="toast-close" onclick="this.parentElement.parentElement.classList.remove('show');setTimeout(()=>this.parentElement.parentElement.remove(), 400)">&times;</span>
      </div>
      <div class="toast-body">${msg}</div>
    `;
        toast.innerHTML = tHtml;
        container.appendChild(toast);
        requestAnimationFrame(() => {
            setTimeout(() => toast.classList.add('show'), 50);
        });
        setTimeout(() => {
            if (toast.parentElement) {
                toast.classList.remove('show');
                setTimeout(() => { if (toast.parentElement) toast.remove(); }, 400);
            }
        }, 8000);
    }

    // Make showToast global so other scripts can use it if needed
    window.showRealtimeToast = showToast;
})();

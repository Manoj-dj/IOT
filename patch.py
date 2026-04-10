import os

html_path = "dashboard.html"
with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

# 1. Update Navigation
nav_old = """  <div class="sidebar-section">Navigation</div>
  <div class="sidebar-item active"><i class="fa fa-gauge-high"></i> Live Dashboard</div>
  <div class="sidebar-item"><i class="fa fa-bell"></i> Alert History</div>
  <div class="sidebar-item"><i class="fa fa-chart-line"></i> Analytics</div>
  <div class="sidebar-item"><i class="fa fa-map-pin"></i> Manhole Map</div>
  <div class="sidebar-item"><i class="fa fa-file-lines"></i> Reports</div>"""

nav_new = """  <div class="sidebar-section">Navigation</div>
  <div class="sidebar-item active" onclick="switchView('dashboard', this)"><i class="fa fa-gauge-high"></i> Live Dashboard</div>
  <div class="sidebar-item" onclick="switchView('alerts', this)"><i class="fa fa-bell"></i> Alert History</div>
  <div class="sidebar-item" onclick="switchView('analytics', this)"><i class="fa fa-chart-line"></i> Analytics</div>
  <div class="sidebar-item" onclick="switchView('map', this)"><i class="fa fa-map-pin"></i> Manhole Map</div>
  <div class="sidebar-item" onclick="switchView('reports', this)"><i class="fa fa-file-lines"></i> Reports</div>"""

html = html.replace(nav_old, nav_new)

# 2. Wrap existing content
content_start = """  <!-- CONTENT -->
  <div class="content">

    <!-- WORKER ENTRY BANNER -->"""
    
content_new_start = """  <!-- CONTENT -->
  <div class="content">
    <div id="view-dashboard" class="view-section" style="display:block;">

    <!-- WORKER ENTRY BANNER -->"""

html = html.replace(content_start, content_new_start)

# 3. Add new views before closing content div
content_end = """  </div><!-- /content -->"""

new_views = """
    </div><!-- /view-dashboard -->

    <!-- ALERT HISTORY SECTION -->
    <div id="view-alerts" class="view-section" style="display:none;">
      <div class="section-label"><i class="fa fa-bell" style="margin-right:6px;"></i>System Alert History</div>
      <div class="alerts-card" style="padding:0;">
        <div style="padding:20px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center;">
           <h3 style="font-size:16px;">Past Incidents</h3>
           <button style="padding:6px 12px; background:transparent; color:var(--text); border:1px solid var(--border); border-radius:6px; font-size:12px; cursor:pointer;" onclick="loadFullAlerts()"><i class="fa fa-rotate-right" style="margin-right:5px;"></i>Refresh</button>
        </div>
        <table style="width:100%; border-collapse:collapse; text-align:left; font-size:13px;">
          <thead>
            <tr style="background:var(--surface2); border-bottom:1px solid var(--border);">
              <th style="padding:12px 16px;">Timestamp</th>
              <th style="padding:12px 16px;">Manhole ID</th>
              <th style="padding:12px 16px;">Level</th>
              <th style="padding:12px 16px;">Sensor</th>
              <th style="padding:12px 16px;">Value</th>
              <th style="padding:12px 16px;">Threshold</th>
            </tr>
          </thead>
          <tbody id="full-alert-list">
             <tr><td colspan="6" style="padding:20px;text-align:center;color:var(--muted)">Loading alerts...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ANALYTICS SECTION -->
    <div id="view-analytics" class="view-section" style="display:none;">
      <div class="section-label"><i class="fa fa-chart-line" style="margin-right:6px;"></i>System Analytics</div>
      <div class="charts-row" style="grid-template-columns:1fr; margin-bottom:16px;">
        <div class="chart-card">
          <div class="chart-header">
            <div class="chart-title"><i class="fa fa-history" style="color:var(--accent);margin-right:6px;"></i>Historical Environmental Data (Last 100 Logs)</div>
            <button style="padding:6px 12px; background:var(--surface2); color:white; border:1px solid var(--border); border-radius:6px; font-size:12px; cursor:pointer;" onclick="loadAnalytics()"><i class="fa fa-refresh"></i> Refresh Data</button>
          </div>
          <canvas id="historicalChart" height="80"></canvas>
        </div>
      </div>
    </div>

    <!-- MAP SECTION -->
    <div id="view-map" class="view-section" style="display:none;">
      <div class="section-label"><i class="fa fa-map-pin" style="margin-right:6px;"></i>Live Manhole Map</div>
      <div style="background:var(--surface); border:1px solid var(--border); border-radius:14px; position:relative; height:600px; display:flex; align-items:center; justify-content:center; overflow:hidden;">
         <div style="position:relative; z-index:10; text-align:center;">
           <i class="fa fa-map-location-dot" style="font-size:48px; color:var(--accent); margin-bottom:16px;"></i>
           <h3 style="margin-bottom:8px;">Interactive GIS Integration</h3>
           <p style="color:var(--muted);">In production, this integrates with Leaflet or Mapbox API to show live status pins on a street map.</p>
           <button style="margin-top:20px; padding:10px 20px; background:var(--accent); color:white; border:none; border-radius:8px; cursor:pointer;" onclick="alert('Map module initialized. Pins updated.')"><i class="fa fa-map" style="margin-right:6px;"></i> Load Map Overlay</button>
         </div>
      </div>
    </div>

    <!-- REPORTS SECTION -->
    <div id="view-reports" class="view-section" style="display:none;">
      <div class="section-label"><i class="fa fa-file-lines" style="margin-right:6px;"></i>Compliance & Reports</div>
      
      <div class="sensor-grid" style="grid-template-columns:1fr 1fr;">
         <div class="chart-card">
           <div style="font-size:16px; font-weight:600; margin-bottom:10px;"><i class="fa fa-file-pdf" style="color:#f85149; margin-right:8px;"></i>Monthly Hazard Report</div>
           <p style="color:var(--muted); font-size:13px; margin-bottom:20px; line-height:1.5;">Download the compiled safety compliance report containing all threshold breaches and maintenance activities for the current month.</p>
           <button style="padding:10px 20px; background:var(--accent); color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600;" onclick="alert('Generating Monthly Hazard Report PDF...\\nDone.\\nFile saved to Downloads.')"><i class="fa fa-download" style="margin-right:8px;"></i> Download PDF</button>
         </div>
         <div class="chart-card">
           <div style="font-size:16px; font-weight:600; margin-bottom:10px;"><i class="fa fa-file-csv" style="color:#3fb950; margin-right:8px;"></i>Raw Sensor Data Export</div>
           <p style="color:var(--muted); font-size:13px; margin-bottom:20px; line-height:1.5;">Export raw telemetry data (methane, H2S, water level, etc.) for deeper offline analysis or archival in your data warehouse.</p>
           <button style="padding:10px 20px; background:var(--surface2); color:white; border:1px solid var(--border); border-radius:6px; cursor:pointer; font-weight:600;" onclick="alert('Generating CSV file (1.2MB)...\\nDone.\\nExport saved to Downloads.')"><i class="fa fa-table" style="margin-right:8px;"></i> Export as CSV</button>
         </div>
         <div class="chart-card">
           <div style="font-size:16px; font-weight:600; margin-bottom:10px;"><i class="fa fa-envelope" style="color:var(--blue); margin-right:8px;"></i>Automated Notifications</div>
           <p style="color:var(--muted); font-size:13px; margin-bottom:20px; line-height:1.5;">Configure daily or weekly digests sent automatically to safety inspectors and municipal supervisors via email or SMS.</p>
           <button style="padding:10px 20px; background:var(--surface2); color:white; border:1px solid var(--border); border-radius:6px; cursor:pointer; font-weight:600;" onclick="alert('Notification Settings opened.')"><i class="fa fa-gear" style="margin-right:8px;"></i> Configure Digest</button>
         </div>
      </div>
    </div>
  </div><!-- /content -->"""

html = html.replace(content_end, new_views)

# 4. Add JS for the new views
js_anchor = """// Build manhole sidebar"""
js_new = """// --- VIEW NAVIGATION ---
function switchView(viewId, btnEl) {
  // Update sidebar active class
  document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
  // Update the class of the clicked item specifically
  if(btnEl.classList) {
     btnEl.classList.add('active');
  }
  
  // Hide all views, show selected
  document.querySelectorAll('.view-section').forEach(el => el.style.display = 'none');
  const activeView = document.getElementById('view-' + viewId);
  if (activeView) activeView.style.display = 'block';

  // Load specific view data if needed
  if (viewId === 'alerts') loadFullAlerts();
  if (viewId === 'analytics') loadAnalytics();
}

async function loadFullAlerts() {
  const tbody = document.getElementById('full-alert-list');
  tbody.innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--muted)"><i class="fa fa-spinner fa-spin" style="margin-right:8px;"></i>Loading alerts from server...</td></tr>';
  try {
    const r = await fetch(`${API}/api/alerts?n=100`);
    const data = await r.json();
    
    if (!data || data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:30px;text-align:center;color:var(--green)"><i class="fa fa-check-circle" style="font-size:24px;display:block;margin-bottom:10px;"></i>No alerts found in history. System is completely stable.</td></tr>';
      return;
    }
    
    tbody.innerHTML = data.map(a => `
      <tr style="border-bottom:1px solid var(--border); transition:background 0.2s;" onmouseover="this.style.background='var(--surface2)'" onmouseout="this.style.background='transparent'">
        <td style="padding:12px 16px; color:var(--muted);">${a.timestamp || a.time}</td>
        <td style="padding:12px 16px; font-weight:600; color:var(--blue);">${a.manhole_id || currentMH}</td>
        <td style="padding:12px 16px;">
           <span style="padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; 
                background:${a.level==='DANGER'?'rgba(248,81,73,0.15)':'rgba(210,153,34,0.15)'}; 
                color:${a.level==='DANGER'?'var(--red)':'var(--yellow)'}; border:1px solid;">
             ${a.level}
           </span>
        </td>
        <td style="padding:12px 16px;">${a.label || a.sensor}</td>
        <td style="padding:12px 16px; font-weight:700;">${a.value} ${a.unit}</td>
        <td style="padding:12px 16px; color:var(--muted);">> ${a.threshold} ${a.unit}</td>
      </tr>
    `).join('');
  } catch(e) { 
      tbody.innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--red)"><i class="fa fa-triangle-exclamation" style="margin-right:8px;"></i>Failed to load alerts from server.</td></tr>';
      console.error('Error loading alerts:', e); 
  }
}

let historicalChartInstance = null;
async function loadAnalytics() {
  try {
    const r = await fetch(`${API}/api/logs?n=100`);
    const logs = await r.json();
    
    const labels = logs.map(l => l.timestamp.split(' ')[1]);
    const ch4 = logs.map(l => l.methane);
    const h2s = logs.map(l => l.h2s);
    const water = logs.map(l => l.water_level);
    const temps = logs.map(l => l.temperature);
    
    const ctx = document.getElementById('historicalChart').getContext('2d');
    if (historicalChartInstance) historicalChartInstance.destroy();
    
    historicalChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Methane (ppm)', data: ch4, borderColor: '#f85149', backgrondColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.4 },
          { label: 'H2S (ppm)', data: h2s, borderColor: '#ff7b72', backgrondColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.4 },
          { label: 'Water Level (cm)', data: water, borderColor: '#58a6ff', backgrondColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.4 },
          { label: 'Temp (°C)', data: temps, borderColor: '#f0883e', backgrondColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.4 }
        ]
      },
      options: chartDefaults
    });
  } catch(e) { console.error('Error loading analytics:', e); }
}

// Build manhole sidebar"""

html = html.replace(js_anchor, js_new)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)
print("Patch applied successfully.")
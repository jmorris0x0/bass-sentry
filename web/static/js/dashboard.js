/**
 * Bass Sentry Dashboard JavaScript
 * Real-time monitoring of sound levels, distances, and node health
 * Now with WebSocket for live waveform streaming
 */

class BassSentryDashboard {
    constructor() {
        this.updateInterval = 2000; // 2 seconds
        this.radarCanvas = document.getElementById('radar-canvas');
        this.radarCtx = this.radarCanvas.getContext('2d');
        this.updateCount = 0;
        this.lastUpdateTime = Date.now();

        // Waveform data storage (per location)
        this.waveforms = {};
        this.waveformCanvases = {};

        // WebSocket connection
        this.socket = null;

        this.init();
    }

    async init() {
        // Connect WebSocket for live data
        this.connectWebSocket();

        // Initial data fetch
        await this.fetchAllData();

        // Start update loop for non-realtime data
        setInterval(() => this.fetchAllData(), this.updateInterval);

        // Draw initial radar
        this.drawRadar([]);
    }

    connectWebSocket() {
        // Use Socket.IO client
        this.socket = io();

        this.socket.on('connect', () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus(true);
        });

        this.socket.on('disconnect', () => {
            console.log('WebSocket disconnected');
            this.updateConnectionStatus(false, 'WebSocket disconnected');
        });

        // Live waveform data
        this.socket.on('waveform', (data) => {
            this.handleWaveformData(data);
        });

        // Live level updates
        this.socket.on('level', (data) => {
            this.handleLevelUpdate(data);
        });

        this.socket.on('status', (data) => {
            console.log('Server status:', data);
        });
    }

    handleWaveformData(data) {
        const location = data.location || data.station_id;
        console.log('Received waveform for:', location, 'samples:', data.data?.length);

        // Store waveform data
        this.waveforms[location] = {
            data: data.data,
            isReference: data.is_reference,
            timestamp: data.timestamp,
            lastUpdate: Date.now()
        };

        // Render waveform
        this.renderWaveform(location);
    }

    handleLevelUpdate(data) {
        // Update level display in real-time
        const container = document.getElementById('levels-container');
        const existingCard = container.querySelector(`[data-location="${data.location}"]`);

        const value = data.value || 0;
        const levelClass = value < 75 ? 'level-green' : value < 90 ? 'level-yellow' : 'level-red';

        if (existingCard) {
            existingCard.className = `level-card ${levelClass}`;
            existingCard.querySelector('.value').textContent = value.toFixed(1);
        }
    }

    renderWaveform(location) {
        const container = document.getElementById('waveforms-container');
        const waveformData = this.waveforms[location];

        if (!waveformData) return;

        // Get or create canvas for this location
        let canvasWrapper = container.querySelector(`[data-location="${location}"]`);

        if (!canvasWrapper) {
            // Remove placeholder if present
            const placeholder = container.querySelector('.placeholder');
            if (placeholder) placeholder.remove();

            // Create new waveform card
            canvasWrapper = document.createElement('div');
            canvasWrapper.className = 'waveform-card live';
            canvasWrapper.dataset.location = location;
            canvasWrapper.innerHTML = `
                <canvas class="waveform-canvas" width="400" height="100"></canvas>
                <div class="waveform-info">
                    <span class="waveform-label">${location}${waveformData.isReference ? ' (REF)' : ''}</span>
                    <span class="waveform-status">LIVE</span>
                </div>
            `;
            container.appendChild(canvasWrapper);
        }

        const canvas = canvasWrapper.querySelector('canvas');
        const ctx = canvas.getContext('2d');

        // Draw waveform
        this.drawWaveform(ctx, canvas, waveformData.data, waveformData.isReference);
    }

    drawWaveform(ctx, canvas, data, isReference) {
        const width = canvas.width;
        const height = canvas.height;
        const centerY = height / 2;

        // Clear canvas
        ctx.fillStyle = '#161b22';
        ctx.fillRect(0, 0, width, height);

        // Draw center line
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, centerY);
        ctx.lineTo(width, centerY);
        ctx.stroke();

        if (!data || data.length === 0) return;

        // Normalize data to fit canvas height
        const maxVal = Math.max(...data.map(Math.abs)) || 1;
        const scale = (height / 2 - 10) / maxVal;

        // Draw waveform
        ctx.strokeStyle = isReference ? '#00d9ff' : '#3fb950';
        ctx.lineWidth = 2;
        ctx.beginPath();

        const step = width / data.length;
        data.forEach((val, i) => {
            const x = i * step;
            const y = centerY - (val * scale);
            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();

        // Add glow effect for reference
        if (isReference) {
            ctx.shadowColor = '#00d9ff';
            ctx.shadowBlur = 10;
            ctx.stroke();
            ctx.shadowBlur = 0;
        }
    }

    async fetchAllData() {
        try {
            // Fetch all data in parallel
            const [distances, levels, health, venueContribution] = await Promise.all([
                this.fetchJSON('/api/distances'),
                this.fetchJSON('/api/levels'),
                this.fetchJSON('/api/node-health'),
                this.fetchJSON('/api/venue-contribution')
            ]);

            // Update UI
            this.updateDistances(distances);
            this.updateLevels(levels);
            this.updateHealth(health);
            this.updateVenueContribution(venueContribution);

            // Only fetch correlation images if WebSocket isn't providing live waveforms
            if (!this.socket?.connected || Object.keys(this.waveforms).length === 0) {
                try {
                    const correlationImages = await this.fetchJSON('/api/correlation-images');
                    this.updateWaveforms(correlationImages);
                } catch (e) {
                    // Ignore - WebSocket waveforms are preferred anyway
                }
            }

            this.updateStats(distances, levels, health);
            this.updateConnectionStatus(true);
            this.updateLastUpdate();

        } catch (error) {
            console.error('Failed to fetch data:', error);
            this.updateConnectionStatus(false, error.message);
        }
    }

    async fetchJSON(url) {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    }

    updateDistances(distances) {
        if (!Array.isArray(distances)) return;
        this.drawRadar(distances);
    }

    drawRadar(distances) {
        const canvas = this.radarCanvas;
        const ctx = this.radarCtx;
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const maxRadius = Math.min(centerX, centerY) - 30;

        // Clear canvas
        ctx.fillStyle = '#161b22';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Determine max distance for scaling (auto-scale based on data)
        let maxDistance = 100; // default
        if (distances.length > 0) {
            const maxMeasured = Math.max(...distances.map(d => d.distance_m || 0));
            // Round up to nice number for scale
            if (maxMeasured > 150) maxDistance = 200;
            else if (maxMeasured > 75) maxDistance = 100;
            else if (maxMeasured > 40) maxDistance = 50;
            else maxDistance = 25;
        }

        // Draw concentric circles (distance rings) - auto-scaled
        const ringCount = 4;
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.font = '11px sans-serif';
        ctx.fillStyle = '#8b949e';

        for (let i = 1; i <= ringCount; i++) {
            const ringDist = (maxDistance / ringCount) * i;
            const radius = (ringDist / maxDistance) * maxRadius;
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
            ctx.stroke();

            // Label
            ctx.fillText(`${ringDist.toFixed(0)}m`, centerX + radius + 5, centerY);
        }

        // Draw crosshairs
        ctx.beginPath();
        ctx.moveTo(centerX - maxRadius, centerY);
        ctx.lineTo(centerX + maxRadius, centerY);
        ctx.moveTo(centerX, centerY - maxRadius);
        ctx.lineTo(centerX, centerY + maxRadius);
        ctx.stroke();

        // Draw stage (center point)
        ctx.beginPath();
        ctx.arc(centerX, centerY, 12, 0, Math.PI * 2);
        ctx.fillStyle = '#00d9ff';
        ctx.fill();
        ctx.font = '12px sans-serif';
        ctx.fillStyle = '#f0f6fc';
        ctx.textAlign = 'center';
        ctx.fillText('STAGE', centerX, centerY + 28);

        // Draw distance nodes - auto-distributed around the radar
        // This is plug-and-play: nodes are positioned by their measured distance
        if (distances.length > 0) {
            distances.forEach((node, index) => {
                const distance = node.distance_m || 0;
                const radius = Math.min(distance / maxDistance, 1) * maxRadius;

                // Distribute nodes evenly around the circle based on their index
                // This auto-positions without needing venue map configuration
                const angle = (index / distances.length) * Math.PI * 2 - Math.PI / 2;
                const x = centerX + Math.cos(angle) * radius;
                const y = centerY + Math.sin(angle) * radius;

                // Node circle
                ctx.beginPath();
                ctx.arc(x, y, 10, 0, Math.PI * 2);
                ctx.fillStyle = this.getDistanceColor(distance);
                ctx.fill();

                // Node label (truncate long names)
                ctx.font = '11px sans-serif';
                ctx.fillStyle = '#f0f6fc';
                ctx.textAlign = 'center';
                const labelY = y > centerY ? y + 22 : y - 14;
                let label = node.remote_id || `Node ${index + 1}`;
                if (label.length > 15) label = label.substring(0, 12) + '...';
                ctx.fillText(label, x, labelY);

                // Distance label
                ctx.fillStyle = '#8b949e';
                ctx.font = '10px sans-serif';
                ctx.fillText(`${distance.toFixed(1)}m`, x, labelY + 12);
            });
        } else {
            // Show "waiting for nodes" message
            ctx.fillStyle = '#8b949e';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Waiting for nodes...', centerX, centerY + 60);
        }

        ctx.textAlign = 'left'; // Reset
    }

    getDistanceColor(distance) {
        if (distance < 25) return '#3fb950';  // Green
        if (distance < 50) return '#d29922';  // Yellow
        return '#f85149';  // Red
    }

    getVenueDbColor(venueDb) {
        // Color based on typical noise ordinance thresholds
        if (venueDb < 55) return '#3fb950';  // Green - low
        if (venueDb < 65) return '#d29922';  // Yellow - moderate
        return '#f85149';  // Red - high
    }

    updateVenueContribution(stations) {
        const container = document.getElementById('venue-contribution-container');
        if (!container) return;

        if (!Array.isArray(stations) || stations.length === 0) {
            container.innerHTML = '<p class="placeholder">Waiting for venue contribution data...</p>';
            return;
        }

        container.innerHTML = stations.map(station => {
            const venueDb = station.venue_db;
            const totalDb = station.total_db;
            const la90 = station.la90;
            const audibility = station.venue_audibility;
            const rho = station.correlation_coef;
            const distance = station.distance_m;

            // Determine color based on venue contribution level
            const colorClass = venueDb == null ? 'level-unknown' : venueDb < 55 ? 'level-green' : venueDb < 65 ? 'level-yellow' : 'level-red';

            // Format values with fallbacks
            const venueDbStr = venueDb != null ? venueDb.toFixed(1) : '--';
            const totalDbStr = totalDb != null ? totalDb.toFixed(1) : '--';
            const la90Str = la90 != null ? la90.toFixed(1) : '--';
            const audibilityStr = audibility != null ? (audibility > 0 ? '+' : '') + audibility.toFixed(1) : '--';
            const distanceStr = distance != null ? distance.toFixed(0) : '--';
            const rhoStr = rho != null ? rho.toFixed(2) : '--';

            // Correlation indicator
            const corrStatus = rho != null && Math.abs(rho) > 0.1 ? '✓' : '?';
            const corrClass = rho != null && Math.abs(rho) > 0.1 ? 'confirmed' : 'uncertain';

            return `
                <div class="venue-card ${colorClass}">
                    <div class="venue-header">
                        <span class="venue-location">${station.remote_id || 'Unknown'}</span>
                        <span class="venue-distance">${distanceStr}m</span>
                    </div>
                    <div class="venue-main">
                        <div class="venue-db">${venueDbStr}</div>
                        <div class="venue-unit">dB venue</div>
                    </div>
                    <div class="venue-details">
                        <div class="venue-detail">
                            <span class="detail-label">Total</span>
                            <span class="detail-value">${totalDbStr} dB</span>
                        </div>
                        <div class="venue-detail">
                            <span class="detail-label">Background</span>
                            <span class="detail-value">${la90Str} dB</span>
                        </div>
                        <div class="venue-detail">
                            <span class="detail-label">Audibility</span>
                            <span class="detail-value">${audibilityStr} dB</span>
                        </div>
                        <div class="venue-detail">
                            <span class="detail-label">Correlation</span>
                            <span class="detail-value ${corrClass}">${corrStatus} ${rhoStr}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    updateLevels(levels) {
        const container = document.getElementById('levels-container');
        if (!container) return;

        if (!Array.isArray(levels) || levels.length === 0) {
            container.innerHTML = '<p class="placeholder">No level data available</p>';
            return;
        }

        container.innerHTML = levels.map(level => {
            const value = level.value || 0;
            const levelClass = value < 75 ? 'level-green' : value < 90 ? 'level-yellow' : 'level-red';
            return `
                <div class="level-card ${levelClass}" data-location="${level.location}">
                    <div class="location">${level.location || 'Unknown'}</div>
                    <div class="value">${value.toFixed(1)}</div>
                    <div class="unit">dB ${level.band || ''}</div>
                </div>
            `;
        }).join('');
    }

    updateHealth(nodes) {
        const tbody = document.getElementById('health-tbody');
        if (!Array.isArray(nodes) || nodes.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="placeholder">No nodes connected</td></tr>';
            return;
        }

        tbody.innerHTML = nodes.map(node => {
            const online = node.online;
            const statusClass = online ? 'online' : 'offline';
            const statusText = online ? 'ONLINE' : 'OFFLINE';
            const lastSeen = node.last_seen ? this.formatTime(node.last_seen) : 'Never';

            return `
                <tr>
                    <td>${node.node_name || 'Unknown'}</td>
                    <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                    <td>${lastSeen}</td>
                </tr>
            `;
        }).join('');
    }

    updateWaveforms(images) {
        const container = document.getElementById('waveforms-container');

        // Don't overwrite live WebSocket waveforms
        const liveWaveforms = container.querySelectorAll('.waveform-card.live');
        if (liveWaveforms.length > 0) {
            console.log('Preserving', liveWaveforms.length, 'live waveforms');
            return; // Keep the live waveforms, don't replace with static images
        }

        // Check if we have any waveform data from WebSocket
        if (Object.keys(this.waveforms).length > 0) {
            console.log('Have waveform data, skipping image update');
            return;
        }

        if (!Array.isArray(images) || images.length === 0) {
            // Only show placeholder if no live waveforms
            if (!container.querySelector('.waveform-card')) {
                container.innerHTML = '<p class="placeholder">Waiting for correlation data...</p>';
            }
            return;
        }

        container.innerHTML = images.map(img => {
            const staleClass = img.stale ? 'stale' : '';
            const ageText = img.age_seconds < 60
                ? `${Math.round(img.age_seconds)}s ago`
                : `${Math.round(img.age_seconds / 60)}m ago`;

            // Add cache buster to force refresh
            const cacheBuster = Math.floor(Date.now() / 5000); // Update every 5 seconds

            return `
                <div class="waveform-card ${staleClass}">
                    <img src="/correlation/${img.filename}?t=${cacheBuster}" alt="Correlation: ${img.remote_id}">
                    <div class="waveform-info">
                        <span>${img.remote_id}</span>
                        <span>${ageText}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    updateStats(distances, levels, health) {
        // Nodes online
        const nodesOnline = Array.isArray(health) ? health.filter(n => n.online).length : 0;
        document.getElementById('stat-nodes-online').textContent = nodesOnline;

        // Max distance
        let maxDist = 0;
        if (Array.isArray(distances)) {
            distances.forEach(d => {
                if (d.distance_m > maxDist) maxDist = d.distance_m;
            });
        }
        document.getElementById('stat-max-distance').textContent = maxDist > 0 ? `${maxDist.toFixed(0)}m` : '-';

        // Average level
        let avgLevel = 0;
        if (Array.isArray(levels) && levels.length > 0) {
            avgLevel = levels.reduce((sum, l) => sum + (l.value || 0), 0) / levels.length;
        }
        document.getElementById('stat-avg-level').textContent = avgLevel > 0 ? `${avgLevel.toFixed(0)} dB` : '-';

        // Update rate
        this.updateCount++;
        const now = Date.now();
        const elapsed = (now - this.lastUpdateTime) / 1000;
        if (elapsed > 10) {
            const rate = this.updateCount / elapsed;
            document.getElementById('stat-update-rate').textContent = `${rate.toFixed(1)}/s`;
            this.updateCount = 0;
            this.lastUpdateTime = now;
        }
    }

    updateConnectionStatus(connected, error = null) {
        const indicator = document.getElementById('connection-status');
        const dot = indicator.querySelector('.status-dot');
        const text = indicator.querySelector('.status-text');

        if (connected) {
            dot.className = 'status-dot connected';
            text.textContent = 'Connected';
        } else {
            dot.className = 'status-dot error';
            text.textContent = error || 'Disconnected';
        }
    }

    updateLastUpdate() {
        const el = document.getElementById('last-update');
        const now = new Date();
        el.textContent = `Last update: ${now.toLocaleTimeString()}`;
    }

    formatTime(isoString) {
        try {
            const date = new Date(isoString);
            const now = new Date();
            const diffMs = now - date;
            const diffSec = Math.floor(diffMs / 1000);

            if (diffSec < 60) return `${diffSec}s ago`;
            if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
            return date.toLocaleTimeString();
        } catch {
            return isoString;
        }
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new BassSentryDashboard();
});

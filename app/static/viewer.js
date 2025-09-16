class SessionViewer {
    constructor() {
        this.ws = null;
        this.messageNodes = new Map();
        this.seenItemIds = new Set();

        this.sessionSelect = document.getElementById('sessionSelect');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.status = document.getElementById('status');
        this.messagesContent = document.getElementById('messagesContent');
        this.eventsContent = document.getElementById('eventsContent');
        this.toolsContent = document.getElementById('toolsContent');

        this.refreshBtn.addEventListener('click', () => this.loadSessions());
        this.sessionSelect.addEventListener('change', () => {
            const id = this.sessionSelect.value;
            if (id) {
                this.connectToSession(id);
            }
        });

        this.loadSessions();
    }

    resetView() {
        this.messageNodes.clear();
        this.seenItemIds.clear();
        this.messagesContent.innerHTML = '';
        this.eventsContent.innerHTML = '';
        this.toolsContent.innerHTML = '';
    }

    async loadSessions() {
        try {
            const res = await fetch('/sessions');
            const data = await res.json();
            this.sessionSelect.innerHTML = '<option value="">Select session</option>';
            for (const id of data.sessions) {
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = id;
                this.sessionSelect.appendChild(opt);
            }
        } catch (err) {
            console.error('Failed to load sessions', err);
        }
    }

    connectToSession(sessionId) {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.resetView();
        this.status.textContent = 'Connecting...';
        this.status.className = 'status';
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        this.ws = new WebSocket(`${proto}://${location.host}/ws/${sessionId}/events`);

        this.ws.onopen = () => {
            this.status.textContent = 'Connected';
            this.status.className = 'status connected';
        };
        this.ws.onclose = () => {
            this.status.textContent = 'Disconnected';
            this.status.className = 'status disconnected';
        };
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleRealtimeEvent(data);
        };
    }

    handleRealtimeEvent(event) {
        // Add to raw events pane
        this.addRawEvent(event);

        // Add to tools panel if it's a tool or handoff event
        if (event.type === 'tool_start' || event.type === 'tool_end' || event.type === 'handoff') {
            this.addToolEvent(event);
        }

        // Handle specific event types
        switch (event.type) {
            case 'history_updated':
                this.syncMissingFromHistory(event.history);
                this.updateLastMessageFromHistory(event.history);
                break;
//            case 'history_added':
//                // Append just the new item without clearing the thread.
//                if (event.item) {
//                    this.addMessageFromItem(event.item);
//                }
//                break;
        }
    }
    updateLastMessageFromHistory(history) {
        if (!history || !Array.isArray(history) || history.length === 0) return;
        // Find the last message item in history
        let last = null;
        for (let i = history.length - 1; i >= 0; i--) {
            const it = history[i];
            if (it && it.type === 'message') { last = it; break; }
        }
        if (!last) return;
        const itemId = last.item_id;

        // Extract a text representation (for assistant transcript updates)
        let text = '';
        if (Array.isArray(last.content)) {
            for (const part of last.content) {
                if (!part || typeof part !== 'object') continue;
                if (part.type === 'text' && part.text) text += part.text;
                else if (part.type === 'input_text' && part.text) text += part.text;
                else if ((part.type === 'input_audio' || part.type === 'audio') && part.transcript) text += part.transcript;
            }
        }

        const node = this.messageNodes.get(itemId);
        if (!node) {
            // If we haven't rendered this item yet, append it now.
            this.addMessageFromItem(last);
            return;
        }

        // Update only the text content of the bubble, preserving any images already present.
        const bubble = node.querySelector('.message-bubble');
        if (bubble && text && text.trim()) {
            // If there's an <img>, keep it and only update the trailing caption/text node.
            const hasImg = !!bubble.querySelector('img');
            if (hasImg) {
                // Ensure there is a caption div after the image
                let cap = bubble.querySelector('.image-caption');
                if (!cap) {
                    cap = document.createElement('div');
                    cap.className = 'image-caption';
                    cap.style.marginTop = '0.5rem';
                    bubble.appendChild(cap);
                }
                cap.textContent = text.trim();
            } else {
                bubble.textContent = text.trim();
            }
            this.scrollToBottom();
        }
    }

    syncMissingFromHistory(history) {
        if (!history || !Array.isArray(history)) return;
        for (const item of history) {
            if (!item || item.type !== 'message') continue;
            const id = item.item_id;
            if (!id) continue;
            if (!this.seenItemIds.has(id)) {
                this.addMessageFromItem(item);
            }
        }
    }

    addMessageFromItem(item) {
        try {
            if (!item || item.type !== 'message') return;
            const role = item.role;
            let content = '';
            let imageUrls = [];

            if (Array.isArray(item.content)) {
                for (const contentPart of item.content) {
                    if (!contentPart || typeof contentPart !== 'object') continue;
                    if (contentPart.type === 'text' && contentPart.text) {
                        content += contentPart.text;
                    } else if (contentPart.type === 'input_text' && contentPart.text) {
                        content += contentPart.text;
                    } else if (contentPart.type === 'input_audio' && contentPart.transcript) {
                        content += contentPart.transcript;
                    } else if (contentPart.type === 'audio' && contentPart.transcript) {
                        content += contentPart.transcript;
                    } else if (contentPart.type === 'input_image') {
                        const url = contentPart.image_url || contentPart.url;
                        if (typeof url === 'string' && url) imageUrls.push(url);
                    }
                }
            }

            let node = null;
            if (imageUrls.length > 0) {
                for (const url of imageUrls) {
                    node = this.addImageMessage(role, url, content.trim());
                }
            } else if (content && content.trim()) {
                node = this.addMessage(role, content.trim());
            }
            if (node && item.item_id) {
                this.messageNodes.set(item.item_id, node);
                this.seenItemIds.add(item.item_id);
            }
        } catch (e) {
            console.error('Failed to add message from item:', e, item);
        }
    }

    addMessage(type, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;

        const bubbleDiv = document.createElement('div');
        bubbleDiv.className = 'message-bubble';
        bubbleDiv.textContent = content;

        messageDiv.appendChild(bubbleDiv);
        this.messagesContent.appendChild(messageDiv);
        this.scrollToBottom();

        return messageDiv;
    }

    addImageMessage(role, imageUrl, caption = '') {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;

        const bubbleDiv = document.createElement('div');
        bubbleDiv.className = 'message-bubble';

        const img = document.createElement('img');
        img.src = imageUrl;
        img.alt = 'Uploaded image';
        img.style.maxWidth = '220px';
        img.style.borderRadius = '8px';
        img.style.display = 'block';

        bubbleDiv.appendChild(img);
        if (caption) {
            const cap = document.createElement('div');
            cap.textContent = caption;
            cap.style.marginTop = '0.5rem';
            bubbleDiv.appendChild(cap);
        }

        messageDiv.appendChild(bubbleDiv);
        this.messagesContent.appendChild(messageDiv);
        this.scrollToBottom();

        return messageDiv;
    }

    addUserImageMessage(imageUrl, caption = '') {
        return this.addImageMessage('user', imageUrl, caption);
    }

    addRawEvent(event) {
        const eventDiv = document.createElement('div');
        eventDiv.className = 'event';

        const headerDiv = document.createElement('div');
        headerDiv.className = 'event-header';
        headerDiv.innerHTML = `
            <span>${event.type}</span>
            <span>▼</span>
        `;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'event-content collapsed';
        contentDiv.textContent = JSON.stringify(event, null, 2);

        headerDiv.addEventListener('click', () => {
            const isCollapsed = contentDiv.classList.contains('collapsed');
            contentDiv.classList.toggle('collapsed');
            headerDiv.querySelector('span:last-child').textContent = isCollapsed ? '▲' : '▼';
        });

        eventDiv.appendChild(headerDiv);
        eventDiv.appendChild(contentDiv);
        this.eventsContent.appendChild(eventDiv);

        // Auto-scroll events pane
        this.eventsContent.scrollTop = this.eventsContent.scrollHeight;
    }

    addToolEvent(event) {
        const eventDiv = document.createElement('div');
        eventDiv.className = 'event';

        let title = '';
        let description = '';
        let eventClass = '';

        if (event.type === 'handoff') {
            title = `🔄 Handoff`;
            description = `From ${event.from} to ${event.to}`;
            eventClass = 'handoff';
        } else if (event.type === 'tool_start') {
            title = `🔧 Tool Started`;
            description = `Running ${event.tool}`;
            eventClass = 'tool';
        } else if (event.type === 'tool_end') {
            title = `✅ Tool Completed`;
            description = `${event.tool}: ${event.output || 'No output'}`;
            eventClass = 'tool';
        }

        eventDiv.innerHTML = `
            <div class="event-header ${eventClass}">
                <div>
                    <div style="font-weight: 600; margin-bottom: 2px;">${title}</div>
                    <div style="font-size: 0.8rem; opacity: 0.8;">${description}</div>
                </div>
                <span style="font-size: 0.7rem; opacity: 0.6;">${new Date().toLocaleTimeString()}</span>
            </div>
        `;

        this.toolsContent.appendChild(eventDiv);

        // Auto-scroll tools pane
        this.toolsContent.scrollTop = this.toolsContent.scrollHeight;
    }

    scrollToBottom() {
        this.messagesContent.scrollTop = this.messagesContent.scrollHeight;
    }
}

// Initialize the viewer when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new SessionViewer();
});

class GeorgieChatbot {
    constructor() {
        this.isProcessing = false;
        this.isMinimized = true;
        this.mediaRecorder = null;
        this.chunks = [];
        
        // --- CHANGE 1: Initialize a variable to track the active audio ---
        this.currentAudio = null; 
        
        this.init();
    }

    init() {
        // DOM Elements
        this.chatbot = document.getElementById('chatbot');
        this.messages = document.getElementById('messages');
        this.input = document.getElementById('chat-input');
        this.sendBtn = document.getElementById('send-btn');
        this.toggleBtn = document.getElementById('toggle-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.micBtn = document.getElementById('mic-btn');

        this.chatbot.classList.add('minimized'); 
        this.toggleBtn.textContent = '+'; 
        this.updateHeaderTitle();

        this.bindEvents();
    }

    updateHeaderTitle() {
        const title = document.querySelector('.title');
        if(title) {
            title.innerHTML = `🤖 Concrete – RDC Assistant<br><span style="font-size:12px; font-weight:400; opacity:0.9;">Voice Enabled • Powered by IT Team</span>`;
        }
    }

    bindEvents() {
        this.toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleMinimize();
        });

        this.chatbot.querySelector('.chatbot-header').addEventListener('click', (e) => {
            if (e.target !== this.toggleBtn) this.toggleMinimize();
        });

        this.sendBtn.addEventListener('click', () => this.sendMessage());
        
        this.input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.input.addEventListener('input', () => this.autoResizeInput());

        this.stopBtn.addEventListener('click', () => {
            this.isProcessing = false;
            this.stopAudio(); // Stop audio if stop button is clicked
            this.toggleUI(false);
            this.stopBtn.classList.remove('show');
            this.addMessage('⏹️ Stopped.', 'assistant');
        });

        if (this.micBtn) {
            this.micBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (this.micBtn.classList.contains('recording')) {
                    this.stopRecording();
                } else {
                    this.startRecording();
                }
            });
        }
    }

    // --- CHANGE 2: Helper function to immediately kill audio ---
    stopAudio() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0; // Reset to beginning
            this.currentAudio = null;
        }
    }

    // ============================================================
    // 2. VOICE RECORDING LOGIC
    // ============================================================
    startRecording() {
        // --- CHANGE 3: Stop any ongoing audio immediately when mic is clicked ---
        this.stopAudio();

        if (this.isProcessing) return;

        this.chunks = []; 

        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(stream => {
                let options = { mimeType: 'audio/webm' };
                if (!MediaRecorder.isTypeSupported('audio/webm')) {
                    options = {}; 
                }

                this.mediaRecorder = new MediaRecorder(stream, options);

                this.mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) this.chunks.push(e.data);
                };

                this.mediaRecorder.onstop = () => {
                    const blob = new Blob(this.chunks, { type: 'audio/webm' });
                    
                    if (blob.size > 1000) {
                        this.sendVoiceMessage(blob);
                    } else {
                        console.warn("Audio too short.");
                    }
                    
                    stream.getTracks().forEach(track => track.stop());
                };

                this.mediaRecorder.start(); 
                this.micBtn.classList.add('recording'); 
                this.input.placeholder = "Listening... (Click Mic to Send)";
            })
            .catch(err => {
                console.error("Mic Error:", err);
                this.addMessage("❌ Microphone access denied.", 'assistant');
            });
    }

    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
            this.micBtn.classList.remove('recording');
            this.input.placeholder = "Ask about RDC Concrete...";
        }
    }

    async sendVoiceMessage(audioBlob) {
        this.isProcessing = true;
        this.toggleUI(true);
        
        const listeningMsg = this.addMessage("🎤 *Listening...*", 'user');

        const formData = new FormData();
        formData.append('audio', audioBlob);

        try {
            const response = await fetch('/chat-voice', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();
            listeningMsg.remove();

            if (data.success) {
                this.addMessage("🎤 Voice Query", 'user');
                this.addMessage(data.response_text, 'assistant');
                
                if (data.audio_content) {
                    // --- CHANGE 4: Store the audio object so we can stop it later ---
                    this.stopAudio(); // Safety check
                    this.currentAudio = new Audio("data:audio/mp3;base64," + data.audio_content);
                    
                    // Clear the variable when audio finishes naturally
                    this.currentAudio.onended = () => {
                        this.currentAudio = null;
                    };

                    this.currentAudio.play().catch(e => console.log("Audio play error:", e));
                }
            } else {
                this.addMessage('❌ Error: ' + (data.error || "Unknown error"), 'assistant');
            }
        } catch (error) {
            console.error(error);
            this.addMessage('❌ Connection Error. Is the server running?', 'assistant');
        }

        this.isProcessing = false;
        this.toggleUI(false);
    }

    // ============================================================
    // 3. TEXT MESSAGE LOGIC
    // ============================================================
    async sendMessage() {
        // Also stop audio if user decides to type instead
        this.stopAudio(); 

        const message = this.input.value.trim();
        if (!message || this.isProcessing) return;

        this.addMessage(message, 'user');
        this.input.value = '';
        this.autoResizeInput();
        
        this.isProcessing = true;
        this.stopBtn.classList.add('show');
        this.toggleUI(true);

        try {
            const response = await fetch('/chat', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });

            const data = await response.json();
            this.stopBtn.classList.remove('show');
            
            if (data.success) {
                this.addMessage(data.response, 'assistant');
            } else {
                this.addMessage('❌ Error: ' + data.error, 'assistant');
            }
        } catch (error) {
            this.stopBtn.classList.remove('show');
            this.addMessage('❌ Connection error.', 'assistant');
        }

        this.isProcessing = false;
        this.toggleUI(false);
    }

    // ============================================================
    // 4. UI HELPER METHODS
    // ============================================================
    toggleMinimize() {
        this.isMinimized = !this.isMinimized;
        this.chatbot.classList.toggle('minimized', this.isMinimized);
        this.toggleBtn.textContent = this.isMinimized ? '+' : '−';
    }

    autoResizeInput() {
        this.input.style.height = 'auto';
        this.input.style.height = Math.min(this.input.scrollHeight, 100) + 'px';
    }

    toggleUI(processing) {
        this.input.disabled = processing;
        this.sendBtn.disabled = processing;
        this.sendBtn.style.opacity = processing ? '0.5' : '1';
        if(this.micBtn) {
            this.micBtn.style.opacity = processing ? '0.5' : '1';
            this.micBtn.style.pointerEvents = processing ? 'none' : 'auto';
        }
    }

    addMessage(content, role) {
        const cleanContent = content
            .replace(/\*\*(.*?)\*\*/g, '$1')
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/`(.*?)`/g, '$1');

        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = cleanContent.replace(/\n/g, '<br>');
        
        messageDiv.appendChild(bubble);
        this.messages.appendChild(messageDiv);
        this.messages.scrollTop = this.messages.scrollHeight;

        return messageDiv;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new GeorgieChatbot();
});
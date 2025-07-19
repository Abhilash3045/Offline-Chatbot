const express = require("express");
const session = require("express-session");
const bcrypt = require("bcrypt");
const sqlite3 = require("sqlite3").verbose();
const path = require("path");
const fs = require("fs"); // Added by you, but not explicitly used in the provided snippet. Keep if needed elsewhere.
const bodyParser = require("body-parser");
const axios = require("axios");

const app = express();
const PORT = 3000; // keep your port as you wish

// Middleware
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(session({
    secret: "your_secret_key", // IMPORTANT: Change this to a strong, random string in production
    resave: false,
    saveUninitialized: false,
    cookie: {
        maxAge: 1000 * 60 * 60 * 24 // 24 hours for session
    }
}));

// SQLite DB setup for Node.js server
const db = new sqlite3.Database("./chatbot.db", (err) => {
    if (err) {
        console.error("DB error:", err.message);
        // It's critical to exit if the database cannot be opened
        process.exit(1);
    }
    console.log("Connected to SQLite database: ./chatbot.db");
});

// Create tables if not exist
db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password TEXT
    )`, (err) => {
        if (err) console.error("Error creating users table:", err.message);
        else console.log("Users table checked/created.");
    });
    db.run(`CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        sender TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )`, (err) => {
        if (err) console.error("Error creating chats table:", err.message);
        else console.log("Chats table checked/created.");
    });
});

// Serve static files (like your index.html)
app.use(express.static(path.join(__dirname, "public")));
console.log(`Serving static files from: ${path.join(__dirname, "public")}`);


// Simple middleware to check authentication
function requireAuth(req, res, next) {
    if (!req.session.userId) {
        console.log("Authentication required, redirecting to /signin");
        // For security and clarity, it's better to redirect here
        // and handle specific error messages on the frontend's login page
        return res.redirect("/signin?auth_required=true"); // Added query param for clarity
    }
    next();
}

// Render Sign In page
app.get("/signin", (req, res) => {
    // These session.error lines are no longer directly used if using AJAX for form submissions.
    // They were for flash messages with server-side redirects, which we're changing.
    // const error = req.session.error;
    // req.session.error = null;
    res.sendFile(path.join(__dirname, "public", "signin.html"));
    console.log("Serving signin.html");
});

// Render Login page
app.get("/login", (req, res) => {
    // These session.error lines are no longer directly used if using AJAX for form submissions.
    // const error = req.session.error;
    // req.session.error = null;
    res.sendFile(path.join(__dirname, "public", "login.html"));
    console.log("Serving login.html");
});

// Handle Sign In POST
app.post("/signin", async (req, res) => {
    const { email, password } = req.body;
    console.log(`Attempting signin for email: ${email}`);

    if (!email || !password) {
        // --- Specific error message for missing fields ---
        return res.status(400).json({ error: "Email and password are required." });
    }

    // Check if user exists
    db.get("SELECT * FROM users WHERE email = ?", [email], async (err, row) => {
        if (err) {
            console.error("Database error during signin check:", err.message);
            return res.status(500).json({ error: "Internal server error during signin." });
        }
        if (row) {
            console.log(`Signin failed: Email ${email} already registered.`);
            // --- Specific error message for existing email ---
            return res.status(409).json({ error: "This email is already registered. Please use another mail ID." });
        }
        // Create user with hashed password
        try {
            const hashedPassword = await bcrypt.hash(password, 10);
            db.run("INSERT INTO users (email, password) VALUES (?, ?)", [email, hashedPassword], function(err) {
                if (err) {
                    console.error("Failed to create user:", err.message);
                    return res.status(500).json({ error: "Failed to create user." });
                }
                // Log in the new user immediately
                req.session.userId = this.lastID;
                req.session.email = email;
                console.log(`User ${email} signed in successfully with ID: ${this.lastID}`);
                // --- Success response with redirect URL ---
                return res.json({ success: true, redirectUrl: "/" });
            });
        } catch (hashError) {
            console.error("Error hashing password:", hashError);
            return res.status(500).json({ error: "Internal server error during password processing." });
        }
    });
});

// Handle Login POST
app.post("/login", (req, res) => {
    const { email, password } = req.body;
    console.log(`Attempting login for email: ${email}`);

    if (!email || !password) {
        // --- Specific error message for missing fields ---
        return res.status(400).json({ error: "Email and password are required." });
    }

    db.get("SELECT * FROM users WHERE email = ?", [email], async (err, user) => {
        if (err) {
            console.error("Database error during login check:", err.message);
            return res.status(500).json({ error: "Internal server error during login." });
        }
        if (!user) {
            console.log(`Login failed: User ${email} not found.`);
            // --- Specific error message for email not found ---
            return res.status(401).json({ error: "Invalid email or password." }); // General message for security
        }

        const match = await bcrypt.compare(password, user.password);
        if (!match) {
            console.log(`Login failed: Incorrect password for ${email}.`);
            // --- Specific error message for wrong password ---
            return res.status(401).json({ error: "Wrong password." });
        }

        // Successful login
        req.session.userId = user.id;
        req.session.email = user.email;
        console.log(`User ${user.email} logged in successfully with ID: ${user.id}`);
        // --- Success response with redirect URL ---
        res.json({ success: true, redirectUrl: "/" });
    });
});

// Handle logout
app.post("/logout", (req, res) => {
    req.session.destroy((err) => {
        if (err) {
            console.error("Error destroying session during logout:", err);
            return res.status(500).json({ error: "Logout failed." }); // Send JSON error
        }
        console.log("User logged out, session destroyed.");
        res.json({ success: true, redirectUrl: "/login" }); // Send JSON success with redirect URL
    });
});

// Serve chatbot page only if logged in
app.get("/", requireAuth, (req, res) => {
    res.sendFile(path.join(__dirname, "public", "index.html"));
    console.log(`User ${req.session.email} accessed chatbot page.`);
});

// Endpoint to get chat history for current user
app.get("/history", requireAuth, (req, res) => {
    db.all("SELECT message, sender, timestamp FROM chats WHERE user_id = ? ORDER BY timestamp ASC", [req.session.userId], (err, rows) => {
        if (err) {
            console.error("Failed to load chat history:", err.message);
            return res.status(500).json({ error: "Failed to load chat history." });
        }
        console.log(`Loaded ${rows.length} chat history entries for user ID: ${req.session.userId}`);
        res.json({ history: rows });
    });
});

// Endpoint to save chat message
app.post("/save_message", requireAuth, (req, res) => {
    const { message, sender } = req.body;
    if (!message || !sender) {
        console.warn("Attempt to save invalid message data:", req.body);
        return res.status(400).json({ error: "Invalid message data." });
    }

    db.run("INSERT INTO chats (user_id, message, sender) VALUES (?, ?, ?)", [req.session.userId, message, sender], function(err) {
        if (err) {
            console.error("Failed to save message:", err.message);
            return res.status(500).json({ error: "Failed to save message." });
        }
        console.log(`Message saved for user ID ${req.session.userId}: '${message}' (${sender})`);
        res.json({ success: true });
    });
});

// Proxy AI requests to your Flask backend at port 5000
app.post("/get", requireAuth, async (req, res) => {
    try {
        console.log("Forwarding request to Flask AI backend...");
        const response = await axios.post("http://localhost:5000/get", {
            ...req.body, // Include the original request body
            userId: req.session.userId // Add the userId from the session
        }, { timeout: 180000 }); // Increased timeout to 180 seconds
        console.log("Received response from Flask AI backend.");
        res.json(response.data);
    } catch (err) {
        console.error("AI backend communication error:", err.message);
        if (err.code === 'ECONNREFUSED') {
            console.error("Flask backend is likely not running or not accessible at http://localhost:5000.");
        } else if (err.code === 'ERR_BAD_RESPONSE' || err.response) {
            console.error("Flask backend responded with an error status:", err.response ? err.response.status : 'N/A', err.response ? err.response.data : 'N/A');
        } else if (err.code === 'ECONNABORTED') {
            console.error("Request to Flask backend timed out.");
        }
        res.status(500).json({ error: "AI backend error" });
    }
});

app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
    console.log(`\u2705 Node.js server is ready.`);
});
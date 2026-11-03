import net from 'node:net';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import process from 'node:process';

const SOCKET_PATH = process.argv[2];
const MODE = process.argv[3];

if (!SOCKET_PATH || (MODE !== 'parent' && MODE !== 'child')) {
  console.error('Usage: fixture.mjs SOCKET_PATH parent|child');
  process.exit(1);
}

function readProcFile(path) {
  try {
    return fs.readFileSync(path, 'utf8').trim();
  } catch (e) {
    console.error(`Failed to read ${path}: ${e.message}`);
    process.exit(1);
  }
}

function getBootId() {
  return readProcFile('/proc/sys/kernel/random/boot_id');
}

function getInvocationId() {
  const id = process.env.INVOCATION_ID;
  if (!id || !/^[0-9a-f]{32}$/.test(id)) {
    console.error('Missing or invalid INVOCATION_ID');
    process.exit(1);
  }
  return id;
}

function getCgroup() {
  return readProcFile('/proc/self/cgroup');
}

function connectToSocket() {
  return new Promise((resolve, reject) => {
    const socket = net.connect(SOCKET_PATH);
    socket.once('connect', () => resolve(socket));
    socket.once('error', (err) => reject(err));
  });
}

function sendNDJSON(socket, obj) {
  const data = JSON.stringify(obj) + '\n';
  socket.write(data);
}

function setupSocketHandler(socket, role, onCommand) {
  socket.setEncoding('utf8');
  let buffer = '';

  socket.on('data', (chunk) => {
    buffer += chunk;
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      
      if (!line.trim()) {
        console.error('Malformed empty control frame');
        process.exit(1);
      }

      let msg;
      try {
        msg = JSON.parse(line);
      } catch (e) {
        console.error(`Malformed message: ${line}`);
        process.exit(1);
      }

      onCommand(msg);
    }
  });

  socket.on('error', (err) => {
    console.error(`Socket error: ${err.message}`);
    process.exit(1);
  });

  socket.on('end', () => {
    console.error('Controller disconnected before explicit release');
    process.exit(1);
  });

  socket.on('close', () => {
    console.error('Socket closed unexpectedly');
    process.exit(1);
  });
}

if (MODE === 'parent') {
  const child = spawn(process.execPath, [process.argv[1], SOCKET_PATH, 'child'], {
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore', 'ipc']
  });

  child.on('error', (err) => {
    console.error(`Child spawn error: ${err.message}`);
    process.exit(1);
  });

  child.on('exit', (code, signal) => {
    console.error(`Child exited prematurely with code ${code} or signal ${signal}`);
    process.exit(1);
  });

  let childReady = false;
  let childPid = null;



  child.on('disconnect', () => {
    if (!childReady) {
      console.error('Child IPC disconnected before ready');
      process.exit(1);
    }
  });

  child.on('message', (msg) => {
    if (childReady || !msg || msg.event !== 'ready') {
      console.error('Unexpected or repeated child IPC readiness');
      process.exit(1);
    }
    if (msg.event === 'ready') {
      if (msg.pid !== child.pid) {
        console.error(`PID mismatch: expected ${child.pid}, got ${msg.pid}`);
        process.exit(1);
      }
      childPid = msg.pid;
      childReady = true;
      
      connectToSocket().then((socket) => {
        const readyObj = {
          event: 'ready',
          role: 'parent',
          pid: process.pid,
          ppid: process.ppid,
          boot_id: getBootId(),
          invocation_id: getInvocationId(),
          cgroup: getCgroup(),
          child_pid: childPid
        };

        sendNDJSON(socket, readyObj);

        setupSocketHandler(socket, 'parent', (msg) => {
          if (msg.action === 'exit-main') {
            process.exit(0);
          } else {
            console.error(`Unknown action for parent: ${msg.action}`);
            process.exit(1);
          }
        });
      }).catch((err) => {
        console.error(`Parent socket connection failed: ${err.message}`);
        process.exit(1);
      });
    }
  });

} else if (MODE === 'child') {
  connectToSocket().then((socket) => {
    const readyObj = {
      event: 'ready',
      role: 'child',
      pid: process.pid,
      ppid: process.ppid,
      boot_id: getBootId(),
      invocation_id: getInvocationId(),
      cgroup: getCgroup()
    };

    sendNDJSON(socket, readyObj);

    process.send({ event: 'ready', pid: process.pid }, (err) => {
      if (err) {
        console.error(`IPC send failed: ${err.message}`);
        process.exit(1);
      }
      process.disconnect();
    });

    setupSocketHandler(socket, 'child', (msg) => {
      if (msg.action === 'release-child') {
        process.exit(0);
      } else {
        console.error(`Unknown action for child: ${msg.action}`);
        process.exit(1);
      }
    });
  }).catch((err) => {
    console.error(`Child socket connection failed: ${err.message}`);
    process.exit(1);
  });
}

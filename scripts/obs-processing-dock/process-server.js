#!/usr/bin/env node
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const HOST = '127.0.0.1';
const PORT = Number(process.env.OBS_DOCK_PORT || 17890);
const DEFAULT_EXE = process.env.OBS_DOCK_EXE
  || '%LOCALAPPDATA%\\Programs\\talks-reducer\\talks-reducer.exe';
const ALLOWED_CODECS = new Set(['h264', 'hevc', 'av1', 'mp3']);

function expandWinEnv(value) {
  return String(value).replace(/%([^%]+)%/g, (_, name) => process.env[name] || `%${name}%`);
}

function resolveExePath(rawPath) {
  const trimmed = String(rawPath || DEFAULT_EXE).trim();
  return path.normalize(expandWinEnv(trimmed));
}

function buildTalksReducerArgs(inputFile, resolution, speed, codec, autoClose) {
  const args = [inputFile];

  if (resolution === '1080p') {
    args.push('--no-small');
  } else if (resolution === '720p') {
    args.push('--small');
  } else if (resolution === '480p') {
    args.push('--small', '--480');
  }

  args.push('--silent-speed', String(speed));
  args.push('--video-codec', codec);

  if (autoClose) {
    args.push('--open-location', '--auto-close');
  }

  return args;
}

function startTalksReducer(exePath, inputFile, resolution, speed, codec, autoClose) {
  const args = buildTalksReducerArgs(inputFile, resolution, speed, codec, autoClose);

  console.log('\n=== New job ===');
  console.log('Executable:', exePath);
  console.log('Input:     ', inputFile);
  console.log('Resolution:', resolution);
  console.log('Speed:     ', `${speed}x`);
  console.log('Codec:     ', codec);
  console.log('Command:   ', exePath, args.map(a => /\s/.test(a) ? JSON.stringify(a) : a).join(' '));

  const child = spawn(exePath, args, { windowsHide: true });

  child.stdout.on('data', data => process.stdout.write(data));
  child.stderr.on('data', data => process.stderr.write(data));

  child.on('error', err => {
    console.error('Failed to start talks-reducer:', err.message);
  });

  child.on('close', code => {
    if (code === 0) {
      console.log(`Done: ${inputFile}`);
    } else {
      console.error(`talks-reducer exited with code ${code}`);
    }
  });
}

function jsonResponse(res, statusCode, body) {
  res.writeHead(statusCode, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error('Request body is too large'));
        req.destroy();
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    return jsonResponse(res, 204, '');
  }

  if (req.url !== '/process' || req.method !== 'POST') {
    return jsonResponse(res, 404, 'Not found');
  }

  try {
    const body = await readBody(req);
    const payload = JSON.parse(body);

    const inputFile = String(payload.file || '').trim();
    const speed = Number(payload.speed);
    const resolution = String(payload.resolution || '').trim();
    const codec = String(payload.codec || 'hevc').trim();
    const autoClose = Boolean(payload.autoClose);
    const exePath = resolveExePath(payload.exe);

    if (!inputFile) return jsonResponse(res, 400, 'Missing file path');
    if (!fs.existsSync(inputFile)) return jsonResponse(res, 400, `File not found: ${inputFile}`);
    if (![1, 5, 10].includes(speed)) return jsonResponse(res, 400, 'Speed must be 1, 5, or 10');
    if (!['1080p', '720p', '480p'].includes(resolution)) {
      return jsonResponse(res, 400, 'Resolution must be 1080p, 720p, or 480p');
    }
    if (!ALLOWED_CODECS.has(codec)) {
      return jsonResponse(res, 400, 'Codec must be h264, hevc, av1, or mp3');
    }
    if (!fs.existsSync(exePath)) return jsonResponse(res, 400, `Executable not found: ${exePath}`);

    startTalksReducer(exePath, inputFile, resolution, speed, codec, autoClose);
    return jsonResponse(res, 202, `Started talks-reducer: ${exePath}`);
  } catch (err) {
    return jsonResponse(res, 500, `Server error: ${err.message}`);
  }
});

server.listen(PORT, HOST, () => {
  console.log(`OBS Processing Dock server: http://${HOST}:${PORT}`);
  console.log(`Default talks-reducer: ${resolveExePath(DEFAULT_EXE)}`);
  console.log('Keep this window open while using the OBS dock.');
});

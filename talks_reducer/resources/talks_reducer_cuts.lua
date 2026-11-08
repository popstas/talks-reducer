-- talks-reducer: mark fragments to remove from the current video.
--   c  start / finish a fragment
--   C  undo the open mark, else the newest fragment
-- Marks go to the file named by the "file" script option (talks-reducer passes
-- a temp file under the user's temp folder, because Lua's io.open is not
-- guaranteed to handle non-ASCII paths on Windows). Run standalone, they go to
-- "<video path>.cuts.json".
local mp = require "mp"
local utils = require "mp.utils"
local options = require "mp.options"
local msg = require "mp.msg"

local opts = { file = "" }
options.read_options(opts, "talks_reducer_cuts")

local marks = {}     -- fragments in insertion order, so undo drops the newest
local pending = nil  -- start of a fragment that is not closed yet
local marks_path = nil
local source_name = ""

local function clock(t)
  local minutes = math.floor(t / 60)
  return string.format("%02d:%04.1f", minutes, t - minutes * 60)
end

local function merged()
  local sorted = {}
  for _, r in ipairs(marks) do sorted[#sorted + 1] = { r[1], r[2] } end
  table.sort(sorted, function(a, b) return a[1] < b[1] end)
  local out = {}
  for _, r in ipairs(sorted) do
    local last = out[#out]
    if last and r[1] <= last[2] then
      if r[2] > last[2] then last[2] = r[2] end
    else
      out[#out + 1] = r
    end
  end
  return out
end

local function show()
  local parts = {}
  for _, r in ipairs(merged()) do
    parts[#parts + 1] = clock(r[1]) .. "–" .. clock(r[2])
  end
  local text = "Cuts: " .. #parts
  if #parts > 0 then text = text .. " | " .. table.concat(parts, ", ") end
  if pending then text = text .. " | [mark " .. clock(pending) .. "…]" end
  mp.osd_message(text, 4)
end

local function save()
  if not marks_path then return end
  local text = utils.format_json({ version = 1, source = source_name, remove = merged() })
  if not text then
    msg.error("cannot encode marks")
    return
  end
  local tmp = marks_path .. ".tmp"
  local f = io.open(tmp, "w")
  if not f then
    msg.error("cannot write " .. tmp)
    return
  end
  f:write(text)
  f:close()
  os.remove(marks_path)
  local ok, err = os.rename(tmp, marks_path)
  if not ok then msg.error("cannot save marks: " .. tostring(err)) end
end

local function load()
  marks, pending = {}, nil
  if not marks_path then return end
  local f = io.open(marks_path, "r")
  if not f then return end
  local data = utils.parse_json(f:read("*a") or "")
  f:close()
  if type(data) ~= "table" or type(data.remove) ~= "table" then return end
  for _, r in ipairs(data.remove) do
    if type(r) == "table" then
      local a, b = tonumber(r[1]), tonumber(r[2])
      if a and b and b > a then marks[#marks + 1] = { a, b } end
    end
  end
end

local function toggle_mark()
  local t = mp.get_property_number("time-pos")
  if not t then return end
  if pending == nil then
    pending = t
  else
    local a, b = pending, t
    if b < a then a, b = b, a end
    pending = nil
    if b - a > 0.01 then
      marks[#marks + 1] = { a, b }
      save()
    end
  end
  show()
end

local function undo()
  if pending ~= nil then
    pending = nil
  elseif #marks > 0 then
    table.remove(marks)
    save()
  end
  show()
end

mp.register_event("file-loaded", function()
  local path = mp.get_property("path") or ""
  source_name = mp.get_property("filename") or ""
  if opts.file ~= "" then
    marks_path = opts.file
  elseif path ~= "" and not path:find("://", 1, true) then
    marks_path = utils.join_path(mp.get_property("working-directory") or "", path) .. ".cuts.json"
  else
    marks_path = nil
  end
  load()
  if #marks > 0 then show() end
end)

mp.add_forced_key_binding("c", "talks-reducer-mark", toggle_mark)
mp.add_forced_key_binding("C", "talks-reducer-undo", undo)
mp.register_event("shutdown", save)

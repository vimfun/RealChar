/**
 * Text-based Chatting sending Components
 * allow users to send text-based messages through the WebSocket connection.
 */
const chatMsgsWindow = document.getElementById('chat-window');

const messageTextarea = document.getElementById('message-input');
const sendButtun = document.getElementById('send-btn');

const disconnectButton = document.getElementById('disconnect');

function chat_print(str, clear) {
  if (clear) {
    chatMsgsWindow.value = str;
    chatMsgsWindow.scrollTop = chatMsgsWindow.scrollHeight;
    return;
  }
  if (/Select your character /.test(str)) return;
  if (/Hi, my friend, what brings you here toda/.test(str)) return;
  chatMsgsWindow.value += str;
  chatMsgsWindow.scrollTop = chatMsgsWindow.scrollHeight;
}

let send = () => chat_print(`!!! Websocket Error !!! : not open`)
let close = () => chat_print(`!!! Websocket Error !!! : not open`)

const sendMsg = () => {
  const msg = messageTextarea.value;
  send(msg)
  messageTextarea.value = "";
}

messageTextarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendMsg();
  }
});

sendButtun.addEventListener("click", sendMsg);
disconnectButton.addEventListener("click", close);


function handle_protocol_msg(message) {
  const matcher = ptn => ptn ? ptn.test(message) : true;

  const protocol = [
    [/^\[end\]\n/, () => chat_print("\n\n")],
    [undefined, () => chat_print(message)],
  ].map(([ptn, fn]) => [matcher(ptn), fn]);

  protocol.reduce((acc, [matched, handle]) => {
    if (acc) return true;
    if (matched) {
      handle();
      return true;
    } else {
      return acc;
    }
  }, false);
}

function initWebSocket(initMsg) {
  var clientId = Math.floor(Math.random() * 1010000);
  var ws_scheme = window.location.protocol == "https:" ? "wss" : "ws";
  var ms = encodeURIComponent(JSON.stringify(initMsg))
  var ws_path = ws_scheme + '://' + window.location.host + `/ws/${clientId}/cfg/${ms}`;

  let socket = new WebSocket(ws_path);
  socket.binaryType = 'arraybuffer';

  socket.onopen = (event) => {
    console.log("successfully connected");
    // socket_send(initMsg);
  };
  socket.onmessage = (event) => handle_protocol_msg(event.data);
  socket.onerror = (error) => console.log(`WebSocket Error: ${error}`);
  socket.onclose = (error) => console.log("Socket closed");

  function socket_send(m) {
    socket.send(JSON.stringify(m));
  }

  return [socket, socket_send];
}

function main(selectedCharacter) {
  const initMsg = { config: { platform: "web", character: selectedCharacter } };

  let [socket, socket_send] = initWebSocket(initMsg)

  // Clear chat textarea
  chat_print("", true);

  return [(msg) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      chat_print(`\nYou> ${msg}\n`);
      socket_send(/\/config/.test(msg) ? msg : { msg: msg });
    } else {
      chat_print(`!!! Websocket Error !!! : ${socket}`)
    }
  }, () => socket.close()];
}

window.addEventListener("load", function () {
  ["#send-btn", "#message-input", "#chat-window"].map(
    selector => document.querySelector(selector).style.display = 'block'
  );
  let selectedCharacter = window.location.search
  let [sender, closer] = main(selectedCharacter ? selectedCharacter.substring(1) : "default");
  send = sender;
  close = closer;
});
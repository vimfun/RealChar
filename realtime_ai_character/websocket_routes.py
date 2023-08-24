import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, WebSocket, WebSocketDisconnect
from requests import Session

from realtime_ai_character.audio.speech_to_text import SpeechToText, get_speech_to_text
from realtime_ai_character.audio.text_to_speech import TextToSpeech, get_text_to_speech
from realtime_ai_character.character_catalog.catalog_manager import (
    CatalogManager,
    get_catalog_manager,
)
from realtime_ai_character.database.connection import get_db
from realtime_ai_character.llm import LLM, AsyncCallbackTextHandler, get_llm
from realtime_ai_character.logger import get_logger
from realtime_ai_character.models.interaction import Interaction
from realtime_ai_character.utils import (
    ConversationHistory,
    build_history,
    get_connection_manager,
)

logger = get_logger(__name__)

router = APIRouter()

manager = get_connection_manager()

GREETING_TXT = 'Hi, my friend, what brings you here today?'


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(
        websocket: WebSocket,
        client_id: int = Path(...),
        api_key: str = Query(None),
        llm_model: str = Query(default=os.getenv('LLM_MODEL_USE', 'gpt-3.5-turbo-16k')),
        db: Session = Depends(get_db),
        catalog_manager: CatalogManager = Depends(get_catalog_manager),
        speech_to_text: SpeechToText = Depends(get_speech_to_text),
        text_to_speech: TextToSpeech = Depends(get_text_to_speech)):
    # basic authentication
    if os.getenv('USE_AUTH', '') and api_key != os.getenv('AUTH_API_KEY'):
        await websocket.close(code=1008, reason="Unauthorized")
        return
    # TODO: replace client_id with user_id completely.
    user_id = str(client_id)
    llm = get_llm(model=llm_model)
    await manager.connect(websocket)
    try:
        # main_task = asyncio.create_task(
        #     handle_receive(websocket, client_id, db, llm, catalog_manager, speech_to_text, text_to_speech))

        await UserChat(user_id=str(client_id),
                    websocket=websocket,
                    catalog_manager=catalog_manager,
                    db=db).start()

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        await manager.broadcast_message(f"User #{user_id} left the chat")

@router.websocket("/ws/{client_id}/cfg/{init_cfg}")
async def websocket_endpoint_configed(
        websocket: WebSocket,
        client_id: int = Path(...),
        init_cfg: str = Path(...),
        api_key: str = Query(None),
        llm_model: str = Query(default=os.getenv('LLM_MODEL_USE', 'gpt-3.5-turbo-16k')),
        db: Session = Depends(get_db),
        catalog_manager: CatalogManager = Depends(get_catalog_manager),
        speech_to_text: SpeechToText = Depends(get_speech_to_text),
        text_to_speech: TextToSpeech = Depends(get_text_to_speech)):
    # basic authentication
    if os.getenv('USE_AUTH', '') and api_key != os.getenv('AUTH_API_KEY'):
        await websocket.close(code=1008, reason="Unauthorized")
        return
    # TODO: replace client_id with user_id completely.
    user_id = str(client_id)
    llm = get_llm(model=llm_model)
    await manager.connect(websocket)
    try:
        cfg = json.loads(init_cfg)["config"]
        await UserChat(user_id=str(client_id),
                    websocket=websocket,
                    catalog_manager=catalog_manager,
                    db=db,
                    platform=cfg['platform'],
                    character_index=cfg['character']).start()

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        await manager.broadcast_message(f"User #{user_id} left the chat")

@dataclass
class UserChat:
    user_id: str
    websocket: WebSocket 
    db: Session
    catalog_manager: CatalogManager
    platform: str = ''
    character_index: int = 0
    character: Any = None
    user_input_template: str = ""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4().hex))
    conversation_history: ConversationHistory = field(default_factory=ConversationHistory)
    llm: LLM = field(default_factory=get_llm)

    async def confirm_platform(self):
        if self.platform:
            return
        data = await self.websocket.receive()
        match data:
            case {'type': 'websocket.receive', 'text': platform}:
                self.platform = platform
                logger.info("User %s:%s connected to server with session_id:%s", self.user_id, self.platform, self.session_id)
            case _:
                raise WebSocketDisconnect('disconnected')

    async def confirm_character(self):
        if self.character:
            return
        # 1. User selected a character
        character_list = list(self.catalog_manager.characters.keys())
        character_message = "\n".join([f"{i+1} - {character}" for i, character in enumerate(character_list)])
        await self.send(f"Select your character by entering the corresponding number:\n{character_message}\n")
        
        if self.character_index:
            self.character_index = int(self.character_index)
            character = self.catalog_manager.get_character(
                character_list[self.character_index - 1])
            self.character = character
            self.conversation_history.system_prompt = character.llm_system_prompt
            self.user_input_template = character.llm_user_prompt
            logger.info("User %s:%s:%s selected character: %s", self.user_id, self.platform, self.session_id, self.character.name)
            return

        while True:
            data = await self.websocket.receive()
            match data:
                case {'type': 'websocket.receive', 'text': character_index}:
                    self.character_index = int(character_index)
                    character = self.catalog_manager.get_character(
                        character_list[self.character_index - 1])
                    self.character = character
                    self.conversation_history.system_prompt = character.llm_system_prompt
                    self.user_input_template = character.llm_user_prompt
                    logger.info("User %s:%s:%s selected character: %s", self.user_id, self.platform, self.session_id, self.character.name)
                    break
                case _:
                    raise WebSocketDisconnect('disconnected')

    async def send(self, msg:str):
        print(msg)
        await manager.send_message(message=msg, websocket=self.websocket)

    def save_interaction(self, msg, response: str, msg_type: str):
        Interaction(
            user_id=self.user_id,
            session_id=self.session_id,
            client_message_unicode=msg,
            server_message_unicode=response,
            platform=self.platform,
            action_type=msg_type
        ).save(self.db)


    async def start(self):
        await self.confirm_platform()
        await self.confirm_character()

        # Greet the user
        await self.send(GREETING_TXT)
        # Send end of the greeting so the client knows when to start listening
        await self.send('[end]\n')

        async def on_new_token(token):
            await self.send(token)

        while True:
            data = await self.websocket.receive()
            match data:
                # handle text message
                case {'type': 'websocket.receive', 'text': text_msg}:
                    # 1. Send message to LLM
                    response = await self.llm.achat(
                        history=build_history(self.conversation_history),
                        user_input=text_msg,
                        user_input_template=self.user_input_template,
                        callback=AsyncCallbackTextHandler(on_new_token),
                        audioCallback=None,
                        character=self.character)
                    await self.send('[end]\n')

                    # 3. Update conversation history
                    self.conversation_history.user.append(text_msg)
                    self.conversation_history.ai.append(response)
                    # 4. Persist interaction in the database
                    self.save_interaction(text_msg, response, "text")
                case _:
                    raise WebSocketDisconnect('disconnected')

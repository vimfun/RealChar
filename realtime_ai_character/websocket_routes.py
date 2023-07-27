import asyncio
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
from realtime_ai_character.llm import (
    LLM,
    AsyncCallbackAudioHandler,
    AsyncCallbackTextHandler,
    get_llm,
)
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
        llm_model: str = Query(default=os.getenv(
            'LLM_MODEL_USE', 'gpt-3.5-turbo-16k')),
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
        main_task = asyncio.create_task(
            UserChat(user_id=str(client_id),
                    websocket=websocket,
                    catalog_manager=catalog_manager,
                    db=db).start()
        )

        await asyncio.gather(main_task)

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
        data = await self.websocket.receive()
        match data:
            case {'type': 'websocket.receive', 'text': platform}:
                self.platform = platform
                logger.info("User %s:%s connected to server with session_id:%s", self.user_id, self.platform, self.session_id)
            case _:
                raise WebSocketDisconnect('disconnected')

    async def confirm_character(self):
        # 1. User selected a character
        character_list = list(self.catalog_manager.characters.keys())
        character_message = "\n".join([f"{i+1} - {character}" for i, character in enumerate(character_list)])
        await self.send(f"Select your character by entering the corresponding number:\n{character_message}\n")

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

        previous_transcript = None
        token_buffer = []
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
                        callback=AsyncCallbackTextHandler(on_new_token, token_buffer),
                        audioCallback=None,
                        character=self.character)
                    await self.send('[end]\n')

                    # 3. Update conversation history
                    self.conversation_history.user.append(text_msg)
                    self.conversation_history.ai.append(response)
                    token_buffer.clear()
                    # 4. Persist interaction in the database
                    self.save_interaction(text_msg, response, "text")
                case _:
                    raise WebSocketDisconnect('disconnected')



async def handle_receive(
        websocket: WebSocket,
        client_id: int,
        db: Session,
        llm: LLM,
        catalog_manager: CatalogManager,
        speech_to_text: SpeechToText,
        text_to_speech: TextToSpeech):
    try:
        conversation_history = ConversationHistory()
        # TODO: clean up client_id once migration is done.
        user_id = str(client_id)
        session_id = str(uuid.uuid4().hex)

        # 0. Receive client platform info (web, mobile, terminal)
        data = await websocket.receive()
        if data['type'] != 'websocket.receive':
            raise WebSocketDisconnect(500, 'disconnected')
        platform = data['text']
        logger.info("User #%s:%s connected to server with session_id %s",
                    user_id, platform, session_id)

        # 1. User selected a character
        character = None
        character_list = list(catalog_manager.characters.keys())
        user_input_template = 'Context:{context}\n User:{query}'
        while not character:
            character_message = "\n".join(
                [f"{i+1} - {character}" for i, character in enumerate(character_list)])
            await manager.send_message(
                message=f"Select your character by entering the corresponding number:\n{character_message}\n",
                websocket=websocket)
            data = await websocket.receive()

            if data['type'] != 'websocket.receive':
                raise WebSocketDisconnect(600, 'disconnected')

            if not character and 'text' in data:
                selection = int(data['text'])
                if selection > len(character_list) or selection < 1:
                    char_keys = ', '.join(catalog_manager.characters.keys())
                    await manager.send_message(
                        message= f"Invalid selection. Select your character [{char_keys}]\n",
                        websocket=websocket)
                    continue
                character = catalog_manager.get_character(
                    character_list[selection - 1])
                conversation_history.system_prompt = character.llm_system_prompt
                user_input_template = character.llm_user_prompt
                logger.info("User #%s selected character: %s", user_id, character.name)

        tts_event = asyncio.Event()
        tts_task = None
        previous_transcript = None
        token_buffer = []

        # Greet the user
        await manager.send_message(message=GREETING_TXT, websocket=websocket)
        tts_task = asyncio.create_task(text_to_speech.stream(
            text=GREETING_TXT,
            websocket=websocket,
            tts_event=tts_event,
            characater_name=character.name,
            first_sentence=True,
        ))
        # Send end of the greeting so the client knows when to start listening
        await manager.send_message(message='[end]\n', websocket=websocket)

        async def on_new_token(token):
            return await manager.send_message(message=token, websocket=websocket)

        async def stop_audio():
            if tts_task and not tts_task.done():
                tts_event.set()
                tts_task.cancel()
                if previous_transcript:
                    conversation_history.user.append(previous_transcript)
                    conversation_history.ai.append(' '.join(token_buffer))
                    token_buffer.clear()
                try:
                    await tts_task
                except asyncio.CancelledError:
                    pass
                tts_event.clear()

        while True:
            data = await websocket.receive()
            if data['type'] != 'websocket.receive':
                raise WebSocketDisconnect('disconnected')

            # handle text message
            if 'text' in data:
                msg_data = data['text']
                # 0. itermidiate transcript starts with [&]
                # 1. Send message to LLM
                response = await llm.achat(
                    history=build_history(conversation_history),
                    user_input=msg_data,
                    user_input_template=user_input_template,
                    callback=AsyncCallbackTextHandler(
                        on_new_token, token_buffer),
                    audioCallback=AsyncCallbackAudioHandler(
                        text_to_speech, websocket, tts_event, character.name),
                    character=character)

                # 2. Send response to client
                await manager.send_message(message='[end]\n', websocket=websocket)

                # 3. Update conversation history
                conversation_history.user.append(msg_data)
                conversation_history.ai.append(response)
                token_buffer.clear()
                # 4. Persist interaction in the database
                Interaction(
                    user_id=user_id,
                    session_id=session_id,
                    client_message_unicode=msg_data,
                    server_message_unicode=response,
                    platform=platform,
                    action_type='text'
                ).save(db)

            # handle binary message(audio)
            elif 'bytes' in data:
                binary_data = data['bytes']
                # 1. Transcribe audio
                transcript: str = speech_to_text.transcribe(
                    binary_data, platform=platform, prompt=character.name).strip()

                # ignore audio that picks up background noise
                if (not transcript or len(transcript) < 2):
                    continue

                # 2. Send transcript to client
                await manager.send_message(message=f'[+]You said: {transcript}', websocket=websocket)

                # 3. stop the previous audio stream, if new transcript is received
                await stop_audio()

                previous_transcript = transcript

                async def tts_task_done_call_back(response):
                    # Send response to client, [=] indicates the response is done
                    await manager.send_message(message='[=]', websocket=websocket)
                    # Update conversation history
                    conversation_history.user.append(transcript)
                    conversation_history.ai.append(response)
                    token_buffer.clear()
                    # Persist interaction in the database
                    Interaction(
                        user_id=user_id,
                        session_id=session_id,
                        client_message_unicode=transcript,
                        server_message_unicode=response,
                        platform=platform,
                        action_type='audio'
                    ).save(db)

                # 4. Send message to LLM
                tts_task = asyncio.create_task(llm.achat(
                    history=build_history(conversation_history),
                    user_input=transcript,
                    user_input_template=user_input_template,
                    callback=AsyncCallbackTextHandler(
                        on_new_token, token_buffer, tts_task_done_call_back),
                    audioCallback=AsyncCallbackAudioHandler(
                        text_to_speech, websocket, tts_event, character.name),
                    character=character)
                )

    except WebSocketDisconnect:
        logger.info("User #%s closed the connection", user_id)
        await manager.disconnect(websocket)
        return

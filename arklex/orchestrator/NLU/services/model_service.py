"""Model interaction service for NLU operations.

This module provides services for interacting with language models,
handling model configuration, and processing model responses.
It manages the lifecycle of model interactions, including initialization,
message formatting, and response processing.
"""

import json
from typing import Dict, Any, Optional, List, Union, Tuple
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from .model_config import ModelConfig
from arklex.utils.model_config import MODEL

from arklex.utils.exceptions import ModelError, ValidationError, APIError
from arklex.utils.logging_utils import LogContext, LOG_MESSAGES, handle_exceptions
from arklex.orchestrator.NLU.core.base import (
    IntentResponse,
    SlotResponse,
    VerificationResponse,
)
from arklex.orchestrator.NLU.services.api_service import APIClientService
from arklex.orchestrator.NLU.utils.validators import (
    validate_intent_response,
    validate_slot_response,
    validate_verification_response,
)

log_context = LogContext(__name__)


class ModelService:
    """Service for interacting with language models.

    This class manages the interaction with language models, handling
    message formatting, response processing, and error handling.

    Key responsibilities:
    - Model initialization and configuration
    - Message formatting and prompt management
    - Response processing and validation
    - Error handling and logging

    Attributes:
        model_config: Configuration for the language model
        model: Initialized model instance
    """

    def __init__(self, model_config: Dict[str, Any]) -> None:
        """Initialize the model service.

        Args:
            model_config: Configuration for the language model

        Raises:
            ModelError: If initialization fails
            ValidationError: If configuration is invalid
        """
        self.model_config = model_config
        self._validate_config()
        try:
            self.api_service = APIClientService(base_url=self.model_config["endpoint"])
            self.model = self._initialize_model()
            log_context.info(
                "ModelService initialized successfully",
                extra={
                    "model_name": model_config.get("model_name"),
                    "operation": "initialization",
                },
            )
        except Exception as e:
            log_context.error(
                LOG_MESSAGES["ERROR"]["INITIALIZATION_ERROR"].format(
                    service="ModelService", error=str(e)
                ),
                extra={
                    "error": str(e),
                    "service": "ModelService",
                    "operation": "initialization",
                },
            )
            raise ModelError(
                "Failed to initialize model service",
                details={
                    "error": str(e),
                    "service": "ModelService",
                    "operation": "initialization",
                },
            )

    def _validate_config(self) -> None:
        """Validate the model configuration.

        Raises:
            ValidationError: If the configuration is invalid
        """
        required_fields = ["model_name", "model_type_or_path"]
        missing_fields = [
            field for field in required_fields if field not in self.model_config
        ]
        if missing_fields:
            log_context.error(
                "Missing required field",
                extra={
                    "missing_fields": missing_fields,
                    "operation": "config_validation",
                },
            )
            raise ValidationError(
                "Missing required field",
                details={
                    "missing_fields": missing_fields,
                    "operation": "config_validation",
                },
            )
        # Use default values for api_key and endpoint if not provided
        if "api_key" not in self.model_config:
            self.model_config["api_key"] = MODEL["api_key"]
        if "endpoint" not in self.model_config:
            self.model_config["endpoint"] = MODEL["endpoint"]

    @handle_exceptions()
    async def process_text(
        self, text: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process text through the model.

        Args:
            text: Input text to process
            context: Optional context information

        Returns:
            Dict[str, Any]: Processed response from the model

        Raises:
            ValidationError: If input validation fails
            ModelError: If model processing fails
        """
        if not text:
            log_context.error(
                "Text cannot be empty",
                extra={
                    "text": text,
                    "operation": "text_processing",
                },
            )
            raise ValidationError(
                "Text cannot be empty",
                details={
                    "text": text,
                    "operation": "text_processing",
                },
            )

        if not isinstance(text, str):
            log_context.error(
                "Invalid input text",
                extra={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "text_processing",
                },
            )
            raise ValidationError(
                "Invalid input text",
                details={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "text_processing",
                },
            )

        try:
            response = await self._make_model_request(
                {
                    "text": text,
                    "context": context,
                    "model": self.model_config["model_name"],
                }
            )
            return response
        except Exception as e:
            log_context.error(
                str(e),
                extra={
                    "error": str(e),
                    "text": text,
                    "operation": "text_processing",
                },
            )
            raise ModelError(
                str(e),
                details={
                    "error": str(e),
                    "text": text,
                    "operation": "text_processing",
                },
            )

    async def _make_model_request(
        self, text: Union[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Make a request to the model.

        Args:
            text: Input text or dictionary to send to the model

        Returns:
            Dict[str, Any]: Model response

        Raises:
            ModelError: If the request fails
        """
        try:
            if isinstance(text, dict):
                prompt = text.get("text", "")
                context = text.get("context", {})
                model = text.get("model", self.model_config.get("model_name"))
                messages = self._format_messages(prompt, context)
            else:
                messages = self._format_messages(text)

            response = await self.model.agenerate([messages])
            return {"result": response.generations[0][0].text}
        except Exception as e:
            log_context.error(
                str(e),
                extra={
                    "error": str(e),
                    "text": text,
                    "operation": "model_request",
                },
            )
            raise ModelError(
                str(e),
                details={
                    "error": str(e),
                    "text": text,
                    "operation": "model_request",
                },
            )

    @handle_exceptions()
    async def predict_intent(self, text: str) -> IntentResponse:
        """Predict intent from input text.

        Args:
            text: Input text to predict intent from

        Returns:
            IntentResponse: Predicted intent and confidence

        Raises:
            ValidationError: If input validation fails
            ModelError: If model prediction fails
        """
        # Validate input
        if not text or not isinstance(text, str):
            log_context.error(
                "Invalid input text",
                extra={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "intent_prediction",
                },
            )
            raise ValidationError(
                "Invalid input text",
                details={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "intent_prediction",
                },
            )

        # Get model response
        response = await self.api_service.get_model_response(
            prompt=text, response_format="intent"
        )

        # Validate response
        if not response or not response.content:
            log_context.error(
                "Empty response from model",
                extra={
                    "response": response,
                    "operation": "intent_prediction",
                },
            )
            raise ModelError(
                "Empty response from model",
                details={
                    "response": response,
                    "operation": "intent_prediction",
                },
            )

        # Parse and validate intent response
        try:
            intent_data = json.loads(response.content)
            validated_response = validate_intent_response(intent_data)
            log_context.info(
                "Intent prediction successful",
                extra={
                    "intent": validated_response.get("intent"),
                    "confidence": validated_response.get("confidence"),
                    "operation": "intent_prediction",
                },
            )
            return IntentResponse(**validated_response)
        except json.JSONDecodeError as e:
            log_context.error(
                "Failed to parse model response",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "intent_prediction",
                },
            )
            raise ModelError(
                "Failed to parse model response",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "intent_prediction",
                },
            )
        except ValidationError as e:
            log_context.error(
                "Invalid intent response format",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "intent_prediction",
                },
            )
            raise ValidationError(
                "Invalid intent response format",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "intent_prediction",
                },
            )

    @handle_exceptions()
    async def fill_slots(self, text: str, intent: str) -> SlotResponse:
        """Fill slots based on input text and intent.

        Args:
            text: Input text to extract slots from
            intent: Intent to use for slot filling

        Returns:
            SlotResponse: Extracted slots and their values

        Raises:
            ValidationError: If input validation fails
            ModelError: If slot filling fails
        """
        # Validate inputs
        if not text or not isinstance(text, str):
            log_context.error(
                "Invalid input text",
                extra={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "slot_filling",
                },
            )
            raise ValidationError(
                "Invalid input text",
                details={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "slot_filling",
                },
            )
        if not intent or not isinstance(intent, str):
            log_context.error(
                "Invalid intent",
                extra={
                    "intent": intent,
                    "type": type(intent).__name__,
                    "operation": "slot_filling",
                },
            )
            raise ValidationError(
                "Invalid intent",
                details={
                    "intent": intent,
                    "type": type(intent).__name__,
                    "operation": "slot_filling",
                },
            )

        # Get model response
        response = await self.api_service.get_model_response(
            prompt=text, response_format="slots", intent=intent
        )

        # Validate response
        if not response or not response.content:
            log_context.error(
                "Empty response from model",
                extra={
                    "response": response,
                    "operation": "slot_filling",
                },
            )
            raise ModelError(
                "Empty response from model",
                details={
                    "response": response,
                    "operation": "slot_filling",
                },
            )

        # Parse and validate slot response
        try:
            slot_data = json.loads(response.content)
            validated_response = validate_slot_response(slot_data)
            log_context.info(
                "Slot filling successful",
                extra={
                    "slots": validated_response.get("slots"),
                    "operation": "slot_filling",
                },
            )
            return SlotResponse(**validated_response)
        except json.JSONDecodeError as e:
            log_context.error(
                "Failed to parse slot response",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_filling",
                },
            )
            raise ModelError(
                "Failed to parse slot response",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_filling",
                },
            )
        except ValidationError as e:
            log_context.error(
                "Invalid slot response format",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_filling",
                },
            )
            raise ValidationError(
                "Invalid slot response format",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_filling",
                },
            )

    @handle_exceptions()
    async def verify_slots(
        self, text: str, slots: Dict[str, Any]
    ) -> VerificationResponse:
        """Verify slots against input text.

        Args:
            text: Input text to verify slots against
            slots: Dictionary of slots to verify

        Returns:
            VerificationResponse: Verification results for each slot

        Raises:
            ValidationError: If input validation fails
            ModelError: If slot verification fails
        """
        # Validate inputs
        if not text or not isinstance(text, str):
            log_context.error(
                "Invalid input text",
                extra={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "slot_verification",
                },
            )
            raise ValidationError(
                "Invalid input text",
                details={
                    "text": text,
                    "type": type(text).__name__,
                    "operation": "slot_verification",
                },
            )
        if not slots or not isinstance(slots, dict):
            log_context.error(
                "Invalid slots",
                extra={
                    "slots": slots,
                    "type": type(slots).__name__,
                    "operation": "slot_verification",
                },
            )
            raise ValidationError(
                "Invalid slots",
                details={
                    "slots": slots,
                    "type": type(slots).__name__,
                    "operation": "slot_verification",
                },
            )

        # Get model response
        response = await self.api_service.get_model_response(
            prompt=text, response_format="verification", slots=slots
        )

        # Validate response
        if not response or not response.content:
            log_context.error(
                "Empty response from model",
                extra={
                    "response": response,
                    "operation": "slot_verification",
                },
            )
            raise ModelError(
                "Empty response from model",
                details={
                    "response": response,
                    "operation": "slot_verification",
                },
            )

        # Parse and validate verification response
        try:
            verification_data = json.loads(response.content)
            validated_response = validate_verification_response(verification_data)
            log_context.info(
                "Slot verification successful",
                extra={
                    "verification": validated_response,
                    "operation": "slot_verification",
                },
            )
            return VerificationResponse(**validated_response)
        except json.JSONDecodeError as e:
            log_context.error(
                "Failed to parse verification response",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_verification",
                },
            )
            raise ModelError(
                "Failed to parse verification response",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_verification",
                },
            )
        except ValidationError as e:
            log_context.error(
                "Invalid verification response format",
                extra={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_verification",
                },
            )
            raise ValidationError(
                "Invalid verification response format",
                details={
                    "error": str(e),
                    "response": response.content,
                    "operation": "slot_verification",
                },
            )

    @handle_exceptions()
    def _initialize_model(self) -> BaseChatModel:
        """Initialize the language model.

        Creates and configures a new model instance based on the service
        configuration.

        Returns:
            Initialized model instance

        Raises:
            ModelError: If model initialization fails
        """
        try:
            model = ModelConfig.get_model_instance(self.model_config)
            return ModelConfig.configure_response_format(model, self.model_config)
        except Exception as e:
            raise ModelError(
                "Failed to initialize model",
                details={
                    "error": str(e),
                    "model_config": self.model_config,
                    "operation": "model_initialization",
                },
            )

    def _format_messages(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> List[Union[HumanMessage, SystemMessage]]:
        """Format messages for the model.

        Args:
            prompt: User prompt to send to the model
            context: Optional context information

        Returns:
            List[Union[HumanMessage, SystemMessage]]: Formatted messages
        """
        messages = []
        if context:
            system_prompt = f"Context: {json.dumps(context)}"
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        return messages

    def _format_intent_definition(
        self, intent_name: str, definition: str, count: int
    ) -> str:
        """Format a single intent definition.

        Args:
            intent_name: Name of the intent
            definition: Intent definition text
            count: Intent number in sequence

        Returns:
            Formatted intent definition string
        """
        return f"{count}) {intent_name}: {definition}\n"

    def _format_intent_exemplars(
        self, intent_name: str, sample_utterances: List[str], count: int
    ) -> str:
        """Format sample utterances for an intent.

        Args:
            intent_name: Name of the intent
            sample_utterances: List of example utterances
            count: Intent number in sequence

        Returns:
            Formatted exemplars string
        """
        if not sample_utterances:
            return ""
        exemplars = "\n".join(sample_utterances)
        return f"{count}) {intent_name}: \n{exemplars}\n"

    def _process_intent(
        self,
        intent_k: str,
        intent_v: List[Dict[str, Any]],
        count: int,
        idx2intents_mapping: Dict[str, str],
    ) -> Tuple[str, str, str, int]:
        """Process a single intent and its variations.

        Args:
            intent_k: Intent key/name
            intent_v: List of intent definitions
            count: Current count for numbering
            idx2intents_mapping: Mapping of indices to intent names

        Returns:
            Tuple containing:
                - definition_str: Formatted definitions
                - exemplars_str: Formatted exemplars
                - intents_choice: Formatted choices
                - new_count: Updated count
        """
        definition_str = ""
        exemplars_str = ""
        intents_choice = ""

        if len(intent_v) == 1:
            intent_name = intent_k
            idx2intents_mapping[str(count)] = intent_name
            definition = intent_v[0].get("attribute", {}).get("definition", "")
            sample_utterances = (
                intent_v[0].get("attribute", {}).get("sample_utterances", [])
            )

            if definition:
                definition_str += self._format_intent_definition(
                    intent_name, definition, count
                )
            if sample_utterances:
                exemplars_str += self._format_intent_exemplars(
                    intent_name, sample_utterances, count
                )
            intents_choice += f"{count}) {intent_name}\n"

            count += 1
        else:
            for idx, intent in enumerate(intent_v):
                intent_name = f"{intent_k}__<{idx}>"
                idx2intents_mapping[str(count)] = intent_name
                definition = intent.get("attribute", {}).get("definition", "")
                sample_utterances = intent.get("attribute", {}).get(
                    "sample_utterances", []
                )

                if definition:
                    definition_str += self._format_intent_definition(
                        intent_name, definition, count
                    )
                if sample_utterances:
                    exemplars_str += self._format_intent_exemplars(
                        intent_name, sample_utterances, count
                    )
                intents_choice += f"{count}) {intent_name}\n"

                count += 1

        return definition_str, exemplars_str, intents_choice, count

    def get_response(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        response_format: Optional[str] = None,
        note: Optional[str] = None,
    ) -> str:
        """Get response from the model.

        Sends a prompt to the model and returns its response as a string.
        Handles message formatting and response validation.

        Args:
            prompt: User prompt to send to the model
            model_config: Optional model configuration parameters. If not provided,
                         uses the instance's model_config.
            system_prompt: Optional system prompt for model context
            response_format: Optional format specification for the response
            note: Optional note for logging purposes

        Returns:
            Model response as string

        Raises:
            ValueError: If model response is invalid or empty
        """
        try:
            # Use instance model_config if none provided
            config = model_config if model_config is not None else self.model_config

            # Format messages with system prompt if provided
            messages = []
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            messages.append(HumanMessage(content=prompt))

            # Get response from model
            response = self.model.invoke(messages)

            if not response or not response.content:
                raise ValueError("Empty response from model")

            if note:
                log_context.info(f"Model response for {note}: {response.content}")

            return response.content
        except Exception as e:
            log_context.error(f"Error getting model response: {str(e)}")
            raise ValueError(f"Failed to get model response: {str(e)}")

    def get_json_response(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get JSON response from the model.

        Sends a prompt to the model and returns its response as a parsed
        JSON object. Handles message formatting and JSON validation.

        Args:
            prompt: User prompt to send to the model
            model_config: Optional model configuration parameters. If not provided,
                         uses the instance's model_config.
            system_prompt: Optional system prompt for model context

        Returns:
            Parsed JSON response

        Raises:
            ValueError: If JSON parsing fails or response is invalid
        """
        try:
            response = self.get_response(prompt, model_config, system_prompt)
            return json.loads(response)
        except json.JSONDecodeError as e:
            log_context.error(f"Error parsing JSON response: {str(e)}")
            raise ValueError(f"Failed to parse JSON response: {str(e)}")
        except Exception as e:
            log_context.error(f"Error getting JSON response: {str(e)}")
            raise ValueError(f"Failed to get JSON response: {str(e)}")

    def format_intent_input(
        self, intents: Dict[str, List[Dict[str, Any]]], chat_history_str: str
    ) -> Tuple[str, Dict[str, str]]:
        """Format input for intent detection.

        Creates a formatted prompt for intent detection based on the
        provided intents and chat history. Also generates a mapping
        from indices to intent names.

        Args:
            intents: Dictionary of intents containing:
                - intent_name: List of intent definitions
                - attribute: Intent attributes (definition, sample_utterances)
            chat_history_str: Formatted chat history

        Returns:
            Tuple containing:
                - formatted_prompt: Formatted prompt for intent detection
                - idx2intents_mapping: Mapping from indices to intent names
        """
        definition_str = ""
        exemplars_str = ""
        intents_choice = ""
        idx2intents_mapping: Dict[str, str] = {}
        count = 1

        for intent_k, intent_v in intents.items():
            def_str, ex_str, choice_str, new_count = self._process_intent(
                intent_k, intent_v, count, idx2intents_mapping
            )
            definition_str += def_str
            exemplars_str += ex_str
            intents_choice += choice_str
            count = new_count

        prompt = f"""Given the following intents and their definitions, determine the most appropriate intent for the user's input.

Intent Definitions:
{definition_str}

Sample Utterances:
{exemplars_str}

Available Intents:
{intents_choice}

Chat History:
{chat_history_str}

Please choose the most appropriate intent by providing the corresponding intent number and intent name in the format of 'intent_number) intent_name'."""

        return prompt, idx2intents_mapping

    def format_slot_input(
        self, slots: List[Dict[str, Any]], context: str, type: str = "chat"
    ) -> Tuple[str, str]:
        """Format input for slot filling.

        Creates a prompt for the model to extract slot values from the given context.
        The prompt includes slot definitions and the context to analyze.

        Args:
            slots: List of slot definitions to fill (can be dict or Pydantic model)
            context: Input context to extract values from
            type: Type of slot filling operation (default: "chat")

        Returns:
            Tuple of (user_prompt, system_prompt)
        """
        # Format slot definitions
        slot_definitions = []
        for slot in slots:
            # Handle both dict and Pydantic model inputs
            if isinstance(slot, dict):
                slot_name = slot.get("name", "")
                slot_type = slot.get("type", "string")
                description = slot.get("description", "")
                required = "required" if slot.get("required", False) else "optional"
                items = slot.get("items", {})
            else:
                slot_name = getattr(slot, "name", "")
                slot_type = getattr(slot, "type", "string")
                description = getattr(slot, "description", "")
                required = (
                    "required" if getattr(slot, "required", False) else "optional"
                )
                items = getattr(slot, "items", {})

            slot_def = f"- {slot_name} ({slot_type}, {required}): {description}"
            if items:
                enum_values = (
                    items.get("enum", [])
                    if isinstance(items, dict)
                    else getattr(items, "enum", [])
                )
                if enum_values:
                    slot_def += f"\n  Possible values: {', '.join(enum_values)}"
            slot_definitions.append(slot_def)

        # Create the prompts
        system_prompt = (
            "You are a slot filling assistant. Your task is to extract specific "
            "information from the given context based on the slot definitions. "
            "Return the extracted values in JSON format."
        )

        user_prompt = (
            f"Context:\n{context}\n\n"
            f"Slot definitions:\n" + "\n".join(slot_definitions) + "\n\n"
            "Please extract the values for the defined slots from the context. "
            "Return the results in JSON format with slot names as keys and "
            "extracted values as values. If a slot value cannot be found, "
            "set its value to null."
        )

        return user_prompt, system_prompt

    def process_slot_response(
        self, response: str, slots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process the model's response for slot filling.

        Parses the model's response and updates the slot values accordingly.

        Args:
            response: Model's response containing extracted slot values
            slots: Original slot definitions (can be dict or Pydantic model)

        Returns:
            Updated list of slots with extracted values

        Raises:
            ValueError: If response parsing fails
        """
        try:
            # Parse the JSON response
            extracted_values = json.loads(response)

            # Update slot values
            for slot in slots:
                # Handle both dict and Pydantic model inputs
                if isinstance(slot, dict):
                    slot_name = slot.get("name", "")
                    if slot_name in extracted_values:
                        slot["value"] = extracted_values[slot_name]
                    else:
                        slot["value"] = None
                else:
                    slot_name = getattr(slot, "name", "")
                    if slot_name in extracted_values:
                        setattr(slot, "value", extracted_values[slot_name])
                    else:
                        setattr(slot, "value", None)

            return slots
        except json.JSONDecodeError as e:
            log_context.error(f"Error parsing slot filling response: {str(e)}")
            raise ValueError(f"Failed to parse slot filling response: {str(e)}")
        except Exception as e:
            log_context.error(f"Error processing slot filling response: {str(e)}")
            raise ValueError(f"Failed to process slot filling response: {str(e)}")


class DummyModelService(ModelService):
    """A dummy model service for testing purposes.

    This class provides mock implementations of model service methods
    for use in testing scenarios.
    """

    def format_slot_input(
        self, slots: List[Dict[str, Any]], context: str, type: str = "chat"
    ) -> Tuple[str, str]:
        """Format slot input for testing.

        Args:
            slots: List of slot definitions
            context: Context string
            type: Type of input format (default: "chat")

        Returns:
            Tuple[str, str]: Formatted input and context
        """
        return super().format_slot_input(slots, context, type)

    def get_response(
        self,
        prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        response_format: Optional[str] = None,
        note: Optional[str] = None,
    ) -> str:
        """Get a mock response for testing.

        Args:
            prompt: Input prompt
            model_config: Optional model configuration
            system_prompt: Optional system prompt
            response_format: Optional response format
            note: Optional note

        Returns:
            str: Mock response for testing
        """
        return "1) others"

    def process_slot_response(
        self, response: str, slots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process mock slot response for testing.

        Args:
            response: Mock response string
            slots: List of slot definitions

        Returns:
            List[Dict[str, Any]]: Processed slot values
        """
        return super().process_slot_response(response, slots)

    def format_verification_input(
        self, slot: Dict[str, Any], chat_history_str: str
    ) -> Tuple[str, str]:
        """Format verification input for testing.

        Args:
            slot: Slot definition
            chat_history_str: Chat history string

        Returns:
            Tuple[str, str]: Formatted input and context
        """
        return super().format_verification_input(slot, chat_history_str)

    def process_verification_response(self, response: str) -> Tuple[bool, str]:
        """Process mock verification response for testing.

        Args:
            response: Mock response string

        Returns:
            Tuple[bool, str]: Verification result and explanation
        """
        return super().process_verification_response(response)

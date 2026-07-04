from string import Formatter

from nevo.ai_gateway.entities import PromptTemplate, RenderedPrompt
from nevo.ai_gateway.errors import PromptVariablesError


class PromptRenderer:
    def render(
        self,
        template: PromptTemplate,
        variables: dict[str, str],
    ) -> RenderedPrompt:
        missing = template.required_variables.difference(variables)
        if missing:
            raise PromptVariablesError
        clean_variables = {
            key: str(value).strip()
            for key, value in variables.items()
        }
        try:
            system_instruction = template.system_template.format_map(
                clean_variables
            )
            user_content = template.user_template.format_map(clean_variables)
        except (KeyError, ValueError) as error:
            raise PromptVariablesError from error
        return RenderedPrompt(
            template=template,
            system_instruction=system_instruction,
            user_content=user_content,
        )

    @staticmethod
    def referenced_variables(template_text: str) -> frozenset[str]:
        return frozenset(
            field_name
            for _, field_name, _, _ in Formatter().parse(template_text)
            if field_name
        )

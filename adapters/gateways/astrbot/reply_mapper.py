"""Map internal reply types to AstrBot MessageEventResult objects.

TextReply -> plain_result / image_result
ImageReply -> image_result
CandidateReply -> plain_result with numbered options
ProgressReply -> plain_result (status)
ErrorReply -> plain_result (error message)
"""
